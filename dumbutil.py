#!/usr/bin/env python3
"""
dumbutil - utils for dumbarb
Copyright (C) 2018 Stanislav Traykov st-at-gmuf-com / GNU GPL3

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

See https://github.com/StanTraykov/dumbarb for more info.
"""

import argparse
import datetime
import hashlib
import inspect
import os
import random
import re
import string
import sys
import textwrap
import time
import zlib


class RandyException(Exception): pass
class Syntax(RandyException): pass
class IllegalMove(RandyException): pass
class UnaccSz(RandyException): pass
class UnknownCommand(RandyException): pass


class Randy:
    """ Very simple bot. Add/modify methods to implement GTP commands.

    Return the value (if the GTP command has output) or simply return, if it
    has none. Receive GTP command parameters as arguments (will also send
    syntax error to GTP client if the number of args is not correct).

    Give methods that should not get a GTP response (and should
    not be included in list_commands) a name that begins with '_'

    Dashes in GTP command names are translated to/from 3 underscores ('___').
    Any (extension) GTP commands with variable arguments can be dispatched
    via _catchall.

    Method arguments named 'color' are automagically GTP-syntax checked.
    """
    GTP_LETTERS = string.ascii_uppercase.replace('I', '')

    def genmove(self, color):
        if self._randf < self._swi.resign:
            return 'resign'
        if self._randf < self._swi.pazz:
            return 'pass'
        if self._randf < self._swi.generate_illegal:
            try:
                # try to play on top of a stone
                return random.choice(list(self._stone_list))
            except IndexError:
                # generate an invalid move in another way
                ltr = self.GTP_LETTERS[random.randrange(0, 25)]
                idx = random.randint(self._b_size + 1, 99)
                return ltr + str(idx)
        for i in range(50):
            randint = random.randrange(self._b_size ** 2)
            x = 1 + randint % self._b_size
            y = 1 + randint // self._b_size
            move = self.GTP_LETTERS[x-1] + str(y)
            if move not in self._stone_list:
                # hey, maybe it's NZ rules!
                self._stone_list.add(move)
                return move
        return 'pass'

    def play(self, color, move):
        if self._randf < self._swi.illegal:
            raise IllegalMove('requested response')
        if move.upper() in ['PASS', 'RESIGN']:
            return
        if move[0].upper() not in self.GTP_LETTERS[:self._b_size]:
            raise IllegalMove('x coordinate outside of board')
        if int(move[1:]) > self._b_size:
            raise IllegalMove('y coordinate outside of board')
        if move.upper() in self._stone_list:
            raise IllegalMove
        self._stone_list.add(move.upper())

    def clear_board(self):
        self._stone_list = set()

    def boardsize(self, size):
        isize = int(size)
        if not 2 <= isize <= 25:
            raise UnaccSz('board size outside supported range')
        self._b_size = isize

    def komi(self, komi):
        self._komi = float(komi)

    def time_settings(self, m, p, c):
        self._t_main, self._t_period, self._t_count = int(m), int(p), int(c)

    # 3 underscores (___) for dash (-)
    def kgs___time_settings(self, b, m, p, c):
        pass

    def time_left(self, color, p, c):
        pass

    def final_score(self):
        col = 'WB'[random.randint(0, 1)]
        pts = random.randint(0, 100) + 0.5
        return '{0}+{1}'.format(col, pts)

    def name(self):
        return 'Randy'

    def version(self):
        return '{0:.2f}'.format(self._randf)

    def protocol_version(self):
        return '2'

    # replace '____' in method names with '-'
    def list_commands(self):
        if self._swi.badlist:
            return 'play\nquit'
        commands = [m.replace('___', '-') for m in dir(self)
                    if not m.startswith('_') and callable(getattr(self, m))]
        return '\n'.join(commands)

    def quit(self):
        self._empty_resp()
        if self._logfile:
            self._logfile.close()
        sys.exit(0)

    def _catchall(self, cargs):
            # implement commands with variable arguments (cargs[0] = command)
            raise UnknownCommand

    def _run(self):
        self._swi = self._randy_arg_parse()
        if self._swi.debug:
            prt_err('Hello! This is Randy, version {0:.2f}.'.format(
                random.uniform(0, 100)))
        if self._swi.logfile:
                self._logfile = open(self._swi.logfile, 'a')

        for line in sys.stdin:
            self._log(line, pre=' IN> ')
            self._randf = random.uniform(0, 100)

            # discard comments / empty lines
            try:
                cmdcmt = line.split('#', maxsplit=1)
                cargs = cmdcmt[0].split()
            except (ValueError, IndexError) as e:
                self._err_resp('huh?: {0}'.format(e))
            if not cargs:
                continue

            # waits

            if self._randf < self._swi.sleep[1]:
                time.sleep(self._swi.sleep[0])

            if self._swi.think:
                x, y = self._swi.think
                time.sleep(random.uniform(x, y))

            # alternative responses / hang / exit

            if self._randf < self._swi.hang:
                while True:
                    pass  # hang

            if self._randf < self._swi.exit:
                sys.exit(123)

            if self._randf < self._swi.error:
                self._err_resp('error shmerror')
                continue

            if self._randf < self._swi.gibberish:
                self._resp('gibberish')
                continue

            # replace '-' in commands with '____'
            cmdsub = cargs[0].replace('-', '___')

            # see if we have a method or going to call catchall
            try:
                method = getattr(self, cmdsub)
            except AttributeError:
                try:
                    self._catchall(cargs)
                except UnknownCommand:
                    self._err_resp('unknown command')
                continue
            try:
                params = inspect.signature(method).parameters
                if len(cargs) - 1 != len(params):
                    raise Syntax('wrong number of arguments')
                # magic-checking of 'color' argument (if there is one)
                try:
                    cpar = list(params.keys()).index('color')
                    color = cargs[cpar+1]
                    if color.upper() not in ['WHITE', 'BLACK', 'W', 'B']:
                        raise Syntax('invalid color: {0}'.format(color))
                except ValueError:
                    pass
                retval = method(*cargs[1:])
                if retval is None:
                    self._empty_resp()
                else:
                    self._resp(retval)
            except IllegalMove:
                self._err_resp('illegal move')
            except UnaccSz:
                self._err_resp('unacceptable size')
            except (ValueError, IndexError, Syntax) as e:
                self._err_resp('syntax error: {0}'.format(e))

    def _resp(self, message=None):
        if message:
            self._resp_raw('= {0}'.format(message))
        else:
            self._empty_resp()

    def _empty_resp(self):
        self._resp_raw('=')

    def _err_resp(self, message=None):
        if message:
            self._resp_raw('? {0}'.format(message))
        else:
            self._resp_raw('? wait what?')

    def _resp_raw(self, string, end='\n\n'):
        response = str(string) + end
        sys.stdout.write(response)
        sys.stdout.flush()
        self._log(response, pre='OUT< ')

    def _log(self, string, pre=''):
        if self._logfile:
            logentry = textwrap.indent(string, pre, lambda x: True)
            self._logfile.write(logentry)

    def __init__(self):
        self._randf= None
        self._logfile = None
        self._swi = None
        self._b_size = 19
        self._komi = 7.5
        self._t_main = 0
        self._t_count = 1
        self._t_period = 5
        self._stone_list = set()

    @staticmethod
    def _randy_arg_parse():
        arg_parser = argparse.ArgumentParser(description='''Randy: GTP-speaking
                bot, misbehaving on request. Probs are not really correct with
                more than one supplied. Additionally, Randy may pass on his
                own, when he cannot find an empty board position in 50 random
                tries.''')
        arg_parser.add_argument(
                '-R', action='store_true', default=0, required=True,
                help='shows you have taste in selecting subprograms')
        arg_parser.add_argument(
                '-X', '--exit', metavar='Pr', type=float, default=0,
                help='exit on any command with Pr%% prob')
        arg_parser.add_argument(
                '-e', '--error', metavar='Pr', type=float, default=0,
                help='reply "? error shmerror" to any command with Pr%% prob')
        arg_parser.add_argument(
                '-g', '--gibberish', metavar='Pr',
                type=float,
                default=0,
                help='reply "= gibberish" to any command with Pr%% prob')
        arg_parser.add_argument(
                '-i', '--illegal', metavar='Pr',
                type=float,
                default=0,
                help='say move is illegal in response to play with Pr%% prob')
        arg_parser.add_argument(
                '-I', '--generate-illegal', metavar='Pr',
                type=float,
                default=0,
                help=('generate illegal moves (taken intersections)'
                      ' with Pr%% prob'))
        arg_parser.add_argument(
                '-r', '--resign', metavar='Pr',
                type=float,
                default=0,
                help='resign in response to genmove with Pr%% prob')
        arg_parser.add_argument(
                '-p', '--pass', dest='pazz', metavar='Pr',
                type=float,
                default=0,
                help='pass in response to genmove with Pr%% prob')
        arg_parser.add_argument(
                '-H', '--hang', metavar='Pr',
                type=float,
                default=0,
                help='start busy loop on any command with Pr%% prob')
        arg_parser.add_argument(
                '-s', '--sleep', metavar=('X', 'Pr'),
                nargs=2,
                type=float,
                default=[0, 0],
                help='sleep for X seconds with Pr/100 prob before responding')
        arg_parser.add_argument(
                '-t', '--think', metavar=('X', 'Y'),
                nargs=2,
                type=float,
                help='"think" between X and Y seconds before responding')
        arg_parser.add_argument(
                '-l', '--logfile', metavar='FILE',
                type=str,
                help='save log to FILE')
        arg_parser.add_argument(
                '-L', '--badlist', action='store_true',
                help='respond to list_commands with only play, quit')
        arg_parser.add_argument(
                '-d', '--debug', action='store_true',
                help='print all sorts of stuff to stderr')
        arg_parser.add_argument(
                '-v', '--version', action='version',
                version='Randy {0:.2f}'.format(random.uniform(0, 100)))
        return arg_parser.parse_args()

# ======== common func ========


def prt_err(message, end='\n'):
    sys.stderr.write(str(message) + end)
    sys.stderr.flush()


def eprint_exit(oserr, fatal=False):
    if fatal:
        prt_err('Fatal error: ' + str(oserr))
        exit(1)
    else:
        prt_err(str(oserr))


# ======== summarizer ========


def summary_cmd(filename, fnum):
    try:
        summary(filename, fnum)
    except OSError as e:
        eprint_exit(e, fatal=True)


def summary(filename, fnum):
    fir = {'name': None, 'B': 0, 'W': 0, 'winW': 0, 'winB': 0, 'win': 0,
           'mov': 0, 'ttt': 0, 'maxtt': 0, 'fvio': 0, 'tvio': 0, 'bad': 0}
    sec = fir.copy()
    insert = list(range(fnum))
    count = 0
    totmoves = 0
    maxmoves = 0
    minmoves = 999
    fset = set()
    with open(filename, 'r') as stream:
        for line in stream:
            field = insert + line.split()

            # game count
            count += 1

            # check for errors
            if len(field) < 20 or {field[4], field[6]} != {'W', 'B'} \
                    or field[20] not in {'None', field[3], field[5]}:
                raise FmtError
            if not fir['name']:
                fir['name'] = field[3]
            if not sec['name']:
                sec['name'] = field[5]
            if fir['name'] != field[3] or sec['name'] != field[5]:
                msg = 'Error: engine(s) changed name (game {0})'
                prt_err(msg.format(count))
                sys.exit(1)
            if field[8] == field[3] and field[4] != field[9][0] or \
                    field[8] == field[5] and field[6] != field[9][0]:
                msg = 'Error: winner/player color mismatch (game {0})'
                prt_err(msg.format(count))
                sys.exit(1)
            if fnum > 1:
                frep = field[14] + field[2] + field[13] + field[16] + field[10]
            else:
                frep = field[1] + field[2] + field[13] + field[16] + field[10]
            if frep in fset:
                msg = 'Error: input includes duplicates! (game {0})'
                prt_err(msg.format(count))
                sys.exit(1)
            fset.add(frep)

            # wins / color totals
            fir[field[4]] += 1             # total with color
            sec[field[6]] += 1             # total with color
            if field[8] == fir['name']:
                fir['win'] += 1            # tot wins
                fir['win' + field[4]] += 1  # color wins
            if field[8] == sec['name']:
                sec['win'] += 1            # tot wins
                sec['win' + field[6]] += 1  # color wins

            # moves, thinking times
            mvs = int(field[10])
            totmoves += mvs
            minmoves = min(minmoves, mvs)
            maxmoves = max(maxmoves, mvs)
            fir['mov'] += int(field[11])
            sec['mov'] += int(field[12])
            fir['ttt'] += float(field[13])
            sec['ttt'] += float(field[16])
            fir['maxtt'] = max(fir['maxtt'], float(field[15]))
            sec['maxtt'] = max(sec['maxtt'], float(field[18]))

            for eng in (fir, sec):
                # first vio / bad win
                if eng['name'] == field[20]:
                    eng['fvio'] += 1
                    if eng['name'] == field[8]:  # is winner
                        eng['bad'] += 1
                # total vio
                eng['tvio'] += field[20:].count(eng['name'])

        # formats
        fo1 = ("         {games:7} games, total moves {moves:7}, avg"
              " {avgm:3.1f}, min {minm:3}, max {maxm:3}")
        fo2 = ("    W   B  total wins   wins as W   wins as B  avg t/mv  "
              "max t/mv  viols")
        fo3 = ("{nam:>{wi}}: {w:3} {b:3} {V:3} [{VP:4.1f}%] {W:3} [{WP:4.1f}%]"
              " {B:3} [{BP:4.1f}%] {avgt:8.3f}s {maxt:8.3f}s {fv:2}/{tv:3}")
        fo4 = ("bad wins, being first to exceed time: {fnam} {fb:2};"
              " {snam} {sb:2} (NOT reflected above)")
        fo5 = "total time thunk: {fnam}: {ft}; {snam}: {st}"

        # total thinking times, formatted
        ft = str(datetime.timedelta(seconds=fir['ttt'])).split('.')[0]
        st = str(datetime.timedelta(seconds=sec['ttt'])).split('.')[0]

        # print fo1
        wi = max(len(fir['name']), len(sec['name']))
        print((' ' * wi + fo1).format(
                games=count,
                moves=totmoves,
                avgm=totmoves/count,
                minm=minmoves,
                maxm=maxmoves))

        # print fo2
        print(' ' * wi + fo2)

        # print fo3 for each player
        for eng in (fir, sec):
            print(fo3.format(
                    nam=eng['name'],
                    wi=wi,
                    w=eng['W'], b=eng['B'],
                    V=eng['win'],  VP=100 * eng['win'] / count,
                    W=eng['winW'], WP=100 * eng['winW'] / eng['W'],
                    B=eng['winB'], BP=100 * eng['winB'] / eng['B'],
                    avgt=eng['ttt']/eng['mov'], maxt=eng['maxtt'],
                    fv=eng['fvio'], tv=eng['tvio']))

        # print fo4
        print(fo4.format(
                fnam=fir['name'],
                snam=sec['name'],
                fb=fir['bad'], sb=sec['bad']))

        # print fo5
        print(fo5.format(
                fnam=fir['name'],
                snam=sec['name'],
                ft=ft, st=st))


# ======== duplicates finder ========

MOVERE = re.compile(r"[WB]\[[a-zA-Z]{2,2}\]".encode())


def checksum_sgf(sgf_file, checkfunc):
    with open(sgf_file, 'rb') as f:
        filestring = f.read()
    chksum = checkfunc(b''.join(MOVERE.findall(filestring)))
    return chksum


def finddups(files, checkfunc, checksums, duplicates, skipped, dirname=None):
    count = 0
    for filename in files:
        count += 1
        if filename.lower().endswith('.sgf'):
            if dirname:
                filename = os.path.join(dirname, filename)
            try:
                cksum = checksum_sgf(filename, checkfunc)
            except MemoryError as e:
                print('skipped (memory error): {}'.format(filename))
                skipped.append(filename)
                continue
            if cksum in checksums:
                if cksum not in duplicates:
                    duplicates[cksum] = {checksums[cksum]}
                duplicates[cksum].add(filename)
            else:
                checksums[cksum] = filename
    return count


def finddups_path(path, checkfunc):
    # Python being Python, it's actually cheaper to sha512 straight away than
    # to use a simpler checksum and then check for collisions with sha512.
    before = datetime.datetime.utcnow()
    count = 0
    checksums = {}
    duplicates = {}
    skipped = []
    try:
        for dirname, dirs, files in os.walk(path, onerror=eprint_exit):
            count += finddups(files, checkfunc,
                              checksums, duplicates, skipped, dirname=dirname)
    except OSError as e:
        eprint_exit(e, fatal=True)
    for cksum, dupfiles in duplicates.items():
        print('duplicate games:')
        for filename in dupfiles:
            print('    ' + str(filename))
    if skipped:
        print('skipped:')
        for filename in skipped:
            print('    ' + str(filename))

    dup_count = len(duplicates)
    sum_count = len(checksums)
    time_taken = (datetime.datetime.utcnow() - before).total_seconds()
    msg = ('{total} total file(s), {unique} unique SGF(s), {dup} set(s) of'
           ' duplicates, {skip} skipped file(s).\nTime: {sec}s.\n')
    prt_err(msg.format(total=count, unique=sum_count, dup=dup_count,
                       sec=time_taken, skip=len(skipped)))

# ======== main ========


class ArgError(Exception): pass
class FmtError(Exception): pass


try_fmt = -1
try:
    if sys.argv[1] == '-R':
        Randy()._run()
    if sys.argv[1] in ['-v', '--version']:
        prt_err('dumbutil v.0.2.0')
    elif len(sys.argv) != 3:
        raise ArgError
    elif sys.argv[1] == '-s':
        try_fmt = 2
        summary_cmd(sys.argv[2], 1)
    elif sys.argv[1] == '-S':
        try_fmt = 1
        summary_cmd(sys.argv[2], 2)
    elif sys.argv[1].lower() == '-d':
        finddups_path(sys.argv[2], lambda x: hashlib.sha512(x).digest())
    elif sys.argv[1].lower() == '-3':  # not faster, not collision-safe
        finddups_path(sys.argv[2], zlib.crc32)
    else:
        raise ArgError
except (IndexError, ArgError):
    msg = (
           'usage:\n'
           '{0} -s <logfile>       generate summaries (-S for old syntax)\n'
           '{0} -d <path>          check path and subdirs for duplicate SGFs\n'
           '{0} -R <randy opts>    for Randy (try {0} -R --help)\n'
           '{0} -v|--version       display version information and exit\n'
           '{0} -h|--help          display this message\n')
    prt_err(msg.format(sys.argv[0]))
except FmtError:
    if try_fmt > -1:
        try:
            prt_err('Cannot understand file; trying alternative format...')
            summary(sys.argv[2], try_fmt)
            sys.exit(0)
        except FmtError:
            pass
    prt_err('Failed to recognize file as dumbarb log.')
    sys.exit(1)
