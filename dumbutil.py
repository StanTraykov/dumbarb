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

import datetime
import random, string, sys, time
import argparse

class Syntax(Exception): pass
class IllegalMove(Exception): pass
class UnaccSz(Exception): pass

class Randy:
    """ Very simple bot. Add/modify functions for GTP command responses.

    Give funtions that should not get a GTP response (and should
    not be included in list_commands) a name that begins with '_'
    """
    def genmove(self, cargs):
        if len(cargs) != 2:
                raise Syntax('wrong number of arguments')
        if cargs[1].upper() not in ['WHITE', 'BLACK', 'W', 'B']:
                raise Syntax('invalid color: {0}'.format(cargs[1]))
        if self.randf < self._swi.resign:
            self._resp('resign')
            return
        if self.randf < self._swi.pazz:
            self._resp('pass')
            return
        if self.randf < self._swi.generate_illegal:
            try:
                # try to play on top of a stone
                self._resp(random.choice(list(self._stoneList)))
                return
            except IndexError:
                ltr = self._gtpLetters[random.randrange(0, 25)]
                idx = random.randint(30, 99)
                self._resp(ltr + str(idx))
                return
        for i in range(50):
            randint = random.randrange(self._bSize ** 2)
            x = 1 + randint % 19
            y = 1 + randint // 19
            move = self._gtpLetters[x-1] + str(y)
            if move not in self._stoneList:
                self._resp(move)
                self._stoneList.add(move)
                return
        self._resp('pass')

    def play(self, cargs):
        if len(cargs) != 3:
            raise Syntax('wrong number of arguments')
        if cargs[1].upper() not in ['WHITE', 'BLACK', 'W', 'B']:
            raise Syntax('invalid color: {0}'.format(cargs[1]))
        if self.randf < self._swi.illegal:
            raise IllegalMove('requested response')
        if cargs[2].upper() in ['PASS', 'RESIGN']:
            self._emptyResp()
            return
        if cargs[2][0].upper() not in self._gtpLetters[:self._bSize]:
            raise IllegalMove('coordinates outside board')
        if int(cargs[2][1:]) > self._bSize:
            raise IllegalMove('coordinates outside board')
        if cargs[2].upper() in self._stoneList:
            raise IllegalMove
        self._stoneList.add(cargs[2].upper())
        self._emptyResp()

    def clear_board(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        self._stoneList = set()
        self._emptyResp()

    def boardsize(self, cargs):
        if len(cargs) != 2:
            raise Syntax('wrong number of arguments')
        newSize = int(cargs[1])
        if not 1 < newSize < 25:
            raise UnaccSz('board size outside supported range')
        self._bSize = newSize
        self._emptyResp()

    def komi(self, cargs):
        if len(cargs) != 2:
            raise Syntax('wrong number of arguments')
        self._komi = float(cargs[1])
        self._emptyResp()

    def time_settings(self, cargs):
        if len(cargs) != 4:
            raise Syntax('wrong number of arguments')
        self._tMain, self._tPeriod, self._tCount = cargs[1], cargs[2], cargs[3]
        self._emptyResp()

    # 3 underscores (___) for dash (-)
    def kgs___time_settings(self, cargs):
        if len(cargs) != 5:
            raise Syntax('wrong number of arguments')
        # implement here
        self._emptyResp()

    def time_left(self, cargs):
        if len(cargs) != 4:
            raise Syntax('wrong number of arguments')
        self._emptyResp()

    def final_score(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        col = 'WB'[random.randint(0,1)]
        pts = random.randint(0,100) + 0.5
        self._resp('{0}+{1}'.format(col, pts))

    def name(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        self._resp('Randy')

    def version(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        self._resp('{0:.2f}'.format(self.randf))

    def protocol_version(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        self._resp('2')

    # replace '____' in method names with '-'
    def list_commands(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        methods = [m.replace('___','-') for m in \
            dir(self) if not m.startswith('_') and callable(getattr(self,m))]
        self._resp('\n'.join(methods))

    def quit(self, cargs):
        if len(cargs) != 1:
            raise Syntax('this command cannot have arguments')
        self._emptyResp()
        sys.exit(0)

    def catchall(self, cargs):
        if cargs[0] != 'catchall':
            self._errResp('unknown command')
        else:
            if len(cargs) > 1:
                s = ' Here they are: {0}'.format(cargs[1:])
            else:
                s =''
            self._resp("Got 'em!" + s)

    def _run(self):
        for line in sys.stdin:
            self.randf = random.uniform(0,100)

            # discard comments
            try:
                cmdcmt = line.split('#', maxsplit=1)
                cargs = cmdcmt[0].rstrip().split()
            except (ValueError, IndexError) as e:
                _errResp('huh?: {0}'.format(e))

            # skip empty lines
            if len(cargs) == 0:
                continue

            # waits

            if self.randf < self._swi.sleep[0]:
                time.sleep(self._swi.sleep[1])

            if self._swi.think:
                x, y = self._swi.think
                time.sleep(random.uniform(x, y))

            # alt resps / hang / exit
            if self.randf < self._swi.hang:
                while True:
                    pass # hang

            if self.randf < self._swi.exit:
                sys.exit(123)

            if self.randf < self._swi.error:
                self._errResp('error shmerror')
                continue

            # replace '-' in commands with '____'
            cmdsub=cargs[0].replace('-','___')
            method = getattr(self,cmdsub, self.catchall)

            try:
                method(cargs)
            except (ValueError, IndexError, Syntax) as e:
                self._errResp('syntax error: {0}'.format(e))
            except IllegalMove:
                self._errResp('illegal move')
            except UnaccSz:
                self._errResp('unacceptable size')

    def _resp(self, message=None):
        if message:
            self._respRaw('= {0}'.format(message))
        else:
            self._emptyResp()

    def _emptyResp(self):
        self._respRaw('=')

    def _errResp(self, message=None):
        if message:
            self._respRaw('? {0}'.format(message))
        else:
            self._respRaw('? wait what?')

    def _respRaw(self, string, end='\n\n'):
        sys.stdout.write(str(string) + end)
        sys.stdout.flush()

    def __init__(self):
        args = self._randyArgParse()
        if args.debug:
            prtErr('Hello! This is Randy, version {0:.2f}.'.format(
                random.uniform(0,100)))
        self._swi = args
        self._bSize = 19
        self._komi = 7.5
        self._tMain = 0
        self._tCount = 1
        self._tPeriod = 5
        self._stoneList = set()
        self._gtpLetters = string.ascii_uppercase.replace('I', '')

    @staticmethod
    def _randyArgParse():
        argParser = argparse.ArgumentParser(description='''Randy: GTP-speaking
            bot, misbehaving on request. Probs are not really correct with
            more than one supplied. Additionally, Randy may pass on his own,
            when he cannot find an empty board position in 50 random tries.''')
        argParser.add_argument('-R', action='store_true', default=0,
            required=True,
            help='Shows you have taste in selecting subprograms.')
        argParser.add_argument('-X', '--exit', metavar='Pr',
                type=float,
                default=0,
                help='Exit on any command with Pr%% prob')
        argParser.add_argument('-e', '--error', metavar='Pr',
                type=float,
                default=0,
                help='Reply "? error shmerror" to any command with Pr%% prob')
        argParser.add_argument('-i', '--illegal', metavar='Pr',
                type=float,
                default=0,
                help='Say move is illegal in response to play with Pr%% prob')
        argParser.add_argument('-I', '--generate-illegal', metavar='Pr',
                type=float,
                default=0,
                help='Generate illegal moves (taken intersections) with Pr%% prob')
        argParser.add_argument('-r', '--resign', metavar='Pr',
                type=float,
                default=0,
                help='Resign in response to genmove with Pr%% prob')
        argParser.add_argument('-p', '--pass', dest='pazz', metavar='Pr',
                type=float,
                default=0,
                help='Pass in response to genmove with Pr%% prob')
        argParser.add_argument('-H', '--hang', metavar='Pr',
                type=float,
                default=0,
                help='Start busy loop on any command with Pr%% prob')
        argParser.add_argument('-s', '--sleep', metavar=('X','Pr'),
                nargs=2,
                type=float,
                default=[0, 0],
                help='Sleep for X seconds with Pr/100 prob before responding')
        argParser.add_argument('-t', '--think', metavar=('X','Y'),
                nargs=2,
                type=float,
                help='"Think" between X and Y seconds before responding')
        argParser.add_argument('-l', '--logfile', metavar='FILE',
                type=str,
                help='Save log to FILE')
        argParser.add_argument('-d', '--debug', action='store_true',
                help='Print all sorts of stuff to stderr')
        argParser.add_argument('-v', '--version', action='version',
                version='Randy {0:.2f}'.format(random.uniform(0,100)))
        return argParser.parse_args()

# ======== func ========

def prtErr(msg, end='\n'):
    sys.stderr.write(str(msg) + end)
    sys.stderr.flush()

F1  = "         {games:7} games, total moves {moves:7}, avg {avgm:3.1f}, min {minm:3}, max {maxm:3}"
F2  = "    W   B  total wins   wins as W   wins as B  avg t/mv  max t/mv  viols"
F3  = ("{nam:>{wi}}: {w:3} {b:3} {V:3} [{VP:4.1f}%] {W:3} [{WP:4.1f}%] {B:3} [{BP:4.1f}%]"
      " {avgt:8.3f}s {maxt:8.3f}s {fv:2}/{tv:3}")
F4  = "bad wins, being the first to violate time: {fnam} {fb:2}; {snam} {sb:2}"
F5  = "total time thunk: {fnam}: {ft}; {snam}: {st}"

def summary(filename, fnum):
    fir = {'name': None, 'B': 0, 'W': 0, 'winW': 0, 'winB': 0, 'win': 0, 'mov': 0,
            'ttt': 0, 'maxtt': 0, 'fvio': 0, 'tvio': 0, 'bad': 0}
    sec = fir.copy()
    insert = list(range(fnum))
    count = 0
    totmoves = 0
    maxmoves = 0
    minmoves = 999
    fset = set()
    with open(filename, 'r') as stream:
        for line in stream:
            field = insert + line.strip().split()

            # game count
            count += 1

            # check for errors
            if len(field) < 20 or {field[4], field[6]} != {'W', 'B'} \
                or field[20] not in {'None', field[3], field[5]}:
                raise FmtError
            if not fir['name']: fir['name'] = field[3]
            if not sec['name']: sec['name'] = field[5]
            if fir['name'] != field[3] or sec['name'] != field[5]:
                prtErr('Error: engine(s) changed name (game {0})'.format(count))
                sys.exit(1)
            if  field[8] == field[3] and field[4] != field[9][0] or \
                field[8] == field[5] and field[6] != field[9][0]:
                prtErr('Error: winner/player color mismatch (game {0})'.format(count))
                sys.exit(1)
            if fnum > 1:
                frep = field[14] + field[2] + field[13] + field[16] + field[10]
            else:
                frep =  field[1] + field[2] + field[13] + field[16] + field[10]
            if frep in fset:
                prtErr('Error: input includes duplicates! (game {0})'.format(count))
                sys.exit(1)
            fset.add(frep)

            # wins / color totals
            fir[field[4]] += 1             # total with color
            sec[field[6]] += 1             # total with color
            if field[8] == fir['name']:
                fir['win'] += 1            # tot wins
                fir['win' + field[4]] += 1 # color wins
            if field[8] == sec['name']:
                sec['win'] += 1            # tot wins
                sec['win' + field[6]] += 1 # color wins

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

            # first vio / bad win
            if fir['name'] == field[20]:
                fir['fvio'] += 1
                if fir['name'] == field[8]: #is winner
                    fir['bad'] += 1
            elif sec['name'] == field[20]:
                sec['fvio'] += 1
                if sec['name'] == field[8]: #is winner
                    sec['bad'] += 1

            # total vio
            fir['tvio'] += field[20:].count(fir['name'])
            sec['tvio'] += field[20:].count(sec['name'])

        #print
        wi = max(len(fir['name']), len(sec['name']))
        print((' ' * wi + F1).format(
                games = count,
                moves = totmoves,
                avgm = totmoves/count,
                minm = minmoves,
                maxm = maxmoves))
        print(' ' * wi + F2)
        for eng in (fir, sec):
            print(F3.format(
                    nam = eng['name'],
                    wi = wi,
                    w = eng['W'], b=eng['B'],
                    V = eng['win'],  VP = 100 * eng['win']/count,
                    W = eng['winW'], WP = 100 * eng['winW']/eng['W'],
                    B = eng['winB'], BP = 100 * eng['winB']/eng['B'],
                    avgt = eng['ttt']/eng['mov'], maxt=eng['maxtt'],
                    fv = eng['fvio'], tv = eng['tvio']))
        print(F4.format(
                    fnam = fir['name'],
                    snam = sec['name'],
                    fb = fir['bad'], sb = sec['bad']))
        ft = str(datetime.timedelta(seconds=fir['ttt'])).split('.')[0]
        st = str(datetime.timedelta(seconds=sec['ttt'])).split('.')[0]
        print(F5.format(
                    fnam = fir['name'],
                    snam = sec['name'],
                    ft = ft, st = st))

# ======== main ========

class ArgError(Exception): pass
class FmtError(Exception): pass

tryFmt = -1
try:
    if sys.argv[1] == '-R':
        Randy()._run()
    elif len(sys.argv) != 3:
        raise ArgError
    elif sys.argv[1] == '-s':
        tryFmt = 2
        summary(sys.argv[2], 1)
    elif sys.argv[1] == '-S':
        tryFmt = 1
        summary(sys.argv[2], 2)
    else:
        raise ArgError
except (IndexError, ArgError):
    msg = (
        'usage: {0} -s <logfile>       to generate summaries\n'
        '       {0} -S <logfile>       for old dumbarb 0.2.x files\n'
        '       {0} -R <options>       for Randy (try {0} -R --help)')
    prtErr(msg.format(sys.argv[0]))
except FmtError:
    if tryFmt > -1:
        try:
            prtErr('Cannot understand file; trying alternative format...')
            summary(sys.argv[2], tryFmt)
            sys.exit(0)
        except FmtError:
            prtErr('Failed to recognize file as dumbarb log.')
            sys.exit(1)
    else:
        prtErr('Format Error');
        sys.exit(1)
