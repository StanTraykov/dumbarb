#!/usr/bin/env python3
"""
dumbarb, the semi-smart GTP arbiter
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
import configparser
import contextlib
import datetime
import os
import queue
import re
import shlex
import string
import subprocess
import sys
import textwrap
import threading
import time
import traceback

# CONFIG

DUMBARB = 'dumbarb'
DUMBVER = '0.3.1'

# Maximum number of times an engine should be restarted. This is not an ab-
# solute number. Restarting too quickly or with a high severity argument,
# decreases restart credit by more than 1. Running without problems restores
# restart credit, up to the starting amount, ENGINE_RESTART, after one hour.
ENGINE_RESTART = 10

# results format

FMT_PRE_RES = '{stamp} [{seqno:0{swidth}}] {name1} {col1} {name2} {col2} = '
FMT_WIN_W = '{name:>{nwidth}} W+'
FMT_WIN_B = '{name:>{nwidth}} B+'
FMT_ALT_RES = '{result:>{nwidth}}   '
FMT_REST = ('{reason:6} {moves:3} {mv1:3} {mv2:3}'
            ' {tottt1:11.6f} {avgtt1:9.6f} {maxtt1:9.6f}'
            ' {tottt2:11.6f} {avgtt2:9.6f} {maxtt2:9.6f} VIO: {vio}\n')

RESULT_JIGO = 'Jigo'  # a.k.a. draw
RESULT_NONE = 'None'  # ended w/passes but couldn't/wasn't instructed to score
RESULT_UFIN = 'UFIN'  # game interrupted (illegal move?)
RESULT_OERR = 'ERR'   # some error occured

REASON_ILMV = 'IL'  # one of the engines didn't like a move ('? illegal move')
REASON_JIGO = '=='  # jigo
REASON_NONE = 'XX'  # scoring was not requeted
REASON_SCOR = 'SD'  # scorer problem
REASON_OERR = 'EE'  # some error occured

VIO_NONE = 'None'

# filename format for SGF and other game-specific files

FN_FORMAT = 'game_{num}.{ext}'

# movetimes log

FMT_MTENTRY = '[{seqno:0{swidth}}] {mvs}\n'
FMT_MVTIME = '{move}:{time}'

# SGF

SGF_AP_VER = DUMBARB + ':' + DUMBVER
SGF_BEGIN = ('(;GM[1]FF[4]CA[UTF-8]AP[{0}]RU[{1}]SZ[{2}]KM[{3}]GN[{4}]'
             'PW[{5}]PB[{6}]DT[{7}]EV[{8}]RE[{9}]\n')
SGF_MOVE = ';{color}[{x}{y}]C[{comment}]\n'
SGF_END = ')\n'
SGF_SUBDIR = 'SGFs'

# stderr logging

ERR_SUBDIR = 'stderr'

# engine / desc string naming rules (allowed punctuation, chars, max chars)

ENGALW_PUNC = '+-.,()'
ENGALW_FRPU = '()'
ENGALW_FRST = string.ascii_letters + string.digits + ENGALW_FRPU
ENGALW_CHAR = string.ascii_letters + string.digits + ENGALW_PUNC
ENGALW_MAXC = 20

# engine error/diagnostic messages

ENGINE_BNAM = ('Bad match label/engine name: "{badname}"\n'
               '  Please follow these rules:\n'
               '    * Only ASCII alphanumeric and '
               + ENGALW_PUNC + ' characters\n'
               '    * First character must be alphanumeric or '
               + ENGALW_FRPU + '\n'
               '    * Last character cannot be a dot\n'
               '    * Individual names/labels cannot exceed '
               + str(ENGALW_MAXC) + ' characters')
ENGINE_DIR = 'dir: {dir}'
ENGINE_CMD = 'cmd: {cmd}'
ENGINE_DIAG = '**** {name} version {version}, speaking GTP {protocol_version}'
ENGINE_OK = ' - OK'
ENGINE_FAIL = ' - FAIL'
ENGINE_MSTA = ('{stats[1]} ({stats[3]} W, {stats[5]} B); '
               '{stats[0]} won ({stats[2]} W, {stats[4]} B); '
               'max: {stats[6]:.2f}s, tot: {stats[7]:.0f}s')

# process communication settings

WAIT_QUIT = 1     # seconds to wait for engine to exit before killing process
Q_TIMEOUT = 0.5   # seconds to block at a time when waiting for response

# NON-CONFIG: do not change

REASON_RESIGN = 'Resign'  # } used to produce proper SGF
REASON_TIME = 'Time'    # }
BLACK = 'B'  # } GTP and other stuff rely on these values
WHITE = 'W'  # }

INI_KEYSET = {'cmd', 'wkdir', 'pregame', 'prematch', 'postgame', 'postmatch',
              'quiet', 'logstderr',
              'boardsize', 'komi', 'maintime', 'periodtime', 'periodcount',
              'timesys', 'timetolerance', 'enforcetime',
              'movewait', 'matchwait', 'gamewait',
              'numgames', 'scorer', 'consecutivepasses', 'disablesgf',
              'gtptimeout', 'gtpscorerto', 'gtpgenmoveextra', 'gtpuntimedto'}


class GtpException(Exception):
    """Parent class for GTP exceptions """
    pass
class GtpMissingCommands(GtpException):
    """Engine does not support the required command set for its function """
    pass
class GtpResponseError(GtpException):
    """Engine sent an invalid / unexpected response """
    pass
class GtpIllegalMove(GtpResponseError):
    """Engine replied with '? illegal move' """
    pass
class GtpCannotScore(GtpResponseError):
    """Engine replied with '? cannot score' """
    pass
class GtpProcessError(GtpException):
    """The interprocess communication with the engine failed """
    pass
class GtpTimeout(GtpException):
    """Engine timed out """
    pass
class GtpShutdown(GtpException):
    """Engine is being shut down """
    pass
class ConfigError(Exception):
    """Parsing, value or other error in config """
    pass
class MatchAbort(Exception):
    """Match needs to be aborted """
    pass


class PermanentEngineError(MatchAbort):
    """Not only abort match, but blacklist engine from further matches. """
    def __init__(self, engine_name, message=None):
        if message is None:
            message = 'Permanent engine error; do not try again.'
        super().__init__(message)
        self.engine_name = engine_name


class AllAbort(Exception):
    """Dumbarb needs to exit (e.g. engines misbehave but we cannot kill) """
    pass


class SgfWriter:
    """Collects game data and writes it to an SGF file. """
    GTP_LETTERS = string.ascii_lowercase.replace('i', '')

    def __init__(self, game_settings, white_name, black_name,
                 game_name, event_name):
        """Construct an SgfWriter object.

        Arguments:
        game_settings -- a GameSettings object
        white_name -- name of the white player
        black_name -- name of the black player
        game_name -- name of the game
        event_name -- name of the event
        """
        self.dates_iso = datetime.datetime.now().date().isoformat()
        self.result = None
        self.blacks_turn = True
        self.moves_string = ''
        self.game_settings = game_settings
        self.white_name = white_name
        self.black_name = black_name
        self.game_name = game_name
        self.event_name = event_name
        self.error_encountered = False

    def write_file(self, filename, directory=None):
        """Save a finished game as an SGF file.

        Arguments:
        filename -- output file with or without path
        directory -- directory for file (default: current working dir)
        """
        assert self.result, 'Attempt to write SGF with no result set'
        if directory:
                filename = os.path.join(directory, filename)
        if (self.error_encountered):
            msg = '\n_skipped SGF file due to errors: {0}'
            print_err(msg.format(filename))
            return False
        try:
            with open(filename, 'w', encoding='utf-8') as file:
                begin = SGF_BEGIN.format(
                                SGF_AP_VER,  # 0 AP
                                'Chinese',  # 1 RU
                                self.game_settings.boardsize,  # 2 SZ
                                self.game_settings.komi,  # 3 KM
                                self.game_name,  # 4 GN
                                self.white_name,  # 5 PW
                                self.black_name,  # 6 PB
                                self.dates_iso,  # 7 DT
                                self.event_name,  # 8 EV
                                self.result)  # 9 RE
                file.write(begin)
                file.write(self.moves_string)
                file.write(SGF_END)
        except OSError as e:
            msg = 'n_error writing SGF file "{0}":'
            print_err(msg.format(filename), sub=e)
            return False
        return True

    def add_move(self, coord, comment):
        """Add a move and add today's date to SGF game dates if necessary.

        Arguments:
        coord -- the board coordinates in GTP notation
        """
        if self.error_encountered:
            return False
        today_iso = datetime.datetime.now().date().isoformat()
        if today_iso not in self.dates_iso:
            self.dates_iso += ',' + today_iso
        color = BLACK if self.blacks_turn else WHITE
        if coord.lower() == 'pass':
            letter_right = ''
            letter_down = ''
        else:
            try:
                idx_right = self.GTP_LETTERS.index(coord[0].lower())
                if idx_right > self.game_settings.boardsize:
                    raise ValueError('move outside the board')
                idx_down = abs(int(coord[1:]) - self.game_settings.boardsize)
                if idx_down > self.game_settings.boardsize:
                    raise ValueError('move outside boart board')
                letter_right = string.ascii_lowercase[idx_right]
                letter_down = string.ascii_lowercase[idx_down]
            except ValueError as e:
                msg = 'SGF: Bad move format: "{0}". Ignoring subsequent moves.'
                print_err(msg.format(coord), sub=e)
                self.error_encountered = True
                return False
        mv_string = SGF_MOVE.format(color=color,
                                    x=letter_right,
                                    y=letter_down,
                                    comment=comment)
        self.moves_string += mv_string
        self.blacks_turn = not self.blacks_turn
        return True

    def add_move_list(self, move_list, move_times):
        """Add a list moves using self.add_move.

        Argumetns:
        move_list -- a list of move coordinate strings (GTP notation)

        """
        for move, time in zip(move_list, move_times):
            if move.lower() == 'resign':
                continue
            comment = 'thinking time: {secs}s'
            self.add_move(move, comment=comment.format(secs=time))

    def set_result(self, winner, plus_text=None):
        """Add the game result to the SGF data.

        Arguments:
        winner -- one of WHITE, BLACK, RESULT_JIGO, RESULT_NONE, RESULT_OERR
        plus_text -- text after + if W or B won: Time, Resign, or a number
                    indicating score difference (default None)
        """
        if winner == WHITE:
            self.result = 'W+' + plus_text
        elif winner == BLACK:
            self.result = 'B+' + plus_text
        elif winner == RESULT_JIGO:
            self.result = '0'  # SGF for jigo
        else:
            self.result = '?'  # SGF for 'unknown result'


class GameSettings:
    """Holds go game settings (board size, komi, time settings). """
    def __init__(self, boardsize=19, komi=7.5, main_time=0, period_time=5,
                 period_count=1, time_sys=2):
        """Construct a GameSettings object.

        Arguments:
        boardsize = size of the board (default 19)
        komi = komi (default 7.5)
        main_time = main time in seconds (default 0)
        period_time = period time in seconds (default 5)
        period_count = periods/stones for Japanese/Canad. byo yomi (default 1)
        time_sys = time system: 0=none, 1=absolute, 2=Canadian, 3=Japanese byo
                  yomi (default 2)
        """
        self.boardsize = boardsize
        self.komi = komi
        self.main_time = main_time
        self.period_time = period_time
        self.period_count = period_count
        self.time_sys = time_sys

    def is_untimed(self): return self.time_sys == 0
    def is_abs_time(self): return self.time_sys == 1
    def is_cnd_byo(self): return self.time_sys == 2
    def is_jpn_byo(self): return self.time_sys == 3


class GtpEngine:
    """Talks with a GTP engine via pipes, multi-threaded."""

    def __init__(self, name=None, ein=None, eout=None, eerr=None,
                 gtp_timeout=3, gtp_scorer_to=4, gtp_genmove_extra=15,
                 gtp_genmove_untimed_to=60):
        """Construct a GtpEngine object

        Arguments:
        ein -- engine input stream (default None)
        eout -- engine output stream (default None)
        eerr -- engine error output stream (default None)
        name -- the engine name for logging/display purposes (default None)
        """
        self.name = name
        self.ein = ein
        self.eout = eout
        self.eerr = eerr
        self.gtp_timeout = gtp_timeout
        self.gtp_scorer_to = gtp_scorer_to
        self.gtp_genmove_extra = gtp_genmove_extra
        self.gtp_genmove_untimed_to = gtp_genmove_untimed_to
        self.gtp_debug = False
        self.show_debug = False
        self.color = None
        self.quit_sent = False
        self.thread_eout = None
        self.thread_eerr = None
        self.resp_queue = None
        self.err_file = None
        self.err_lock = threading.Lock()
        self.gtp_down = threading.Event()

    def _threads_init(self):
        """Initialize and run reader threads, response queue

        <Private/protected use> # maybe make a public way to start/stop GtpEng?
        """
        self.gtp_down.clear()

        if self.eout:
            self.resp_queue = queue.Queue()
            self.thread_eout = threading.Thread(
                    name='GTP-rdr',
                    target=self._r_gtp_loop,
                    daemon=True)
            self.thread_eout.start()
        if self.eerr:
            self.thread_eerr = threading.Thread(
                    name='err-rdr',
                    target=self._r_err_loop,
                    daemon=True)
            self.thread_eerr.start()

    def _threads_join(self):
        """Join the threads for shutdown

        """
        if self.show_debug:
            self._engerr('Joining read threads...')
        if self.thread_eout:
            self.thread_eout.join()
        if self.thread_eerr:
            self.thread_eerr.join()

    def _r_gtp_loop(self):
        """Thread: read GTP and put into queue, signal when stream down


        Removes CRs per GTP2, waits for termination with two newlines then
        decodes into a right-stripped string. Sets self.gtp_down when it can no
        longer read.
        """
        bar = bytearray()
        try:
            for byteline in self.eout:
                byteline = byteline.replace(b'\r', b'')
                if byteline != b'\n' or not bar:
                    bar.extend(byteline)
                    continue
                response = bar.decode().rstrip()
                if self.gtp_debug:
                    self._engerr('Received: {0}'.format(response))
                self.resp_queue.put(response)
                bar = bytearray()
            # EOF
            if self.show_debug:
                self._engerr('GTP -EOF-')
            self.gtp_down.set()
        except OSError as e:
            self._engerr('GTP read error: {1}'.format(e))
            self.gtp_down.set()

    def _r_err_loop(self):
        """Thread: Read engine stderr; display it, log to file, or both/none


        Writing/changing the self.err_file is sync'd with a lock.
        """
        try:
            for byteline in self.eerr:
                if not self.suppress_err:
                    self._engerr(byteline.decode().rstrip(), prefix='')
                if self.err_file:
                    with self.err_lock:
                        self.err_file.write(byteline)
            # EOF
            if self.show_debug:
                self._engerr('stderr -EOF-')
        except OSError as e:
            self._engerr('stderr read error: {1}'.format(e))

    def _raw_recv_response(self, timeout):
        """Dequeue a response within timeout, also checking for gtp_down event

        Arguments:
        timeout -- timeout before raising GtpTimeout

        Exceptions: GtpTimeout, GtpShutdown

        """
        begin = datetime.datetime.utcnow()
        retries = 1
        while (datetime.datetime.utcnow() - begin).total_seconds() < timeout:
            try:
                return self.resp_queue.get(block=True, timeout=Q_TIMEOUT)
            except queue.Empty:
                if self.gtp_down.is_set():
                    retries -= 1
                if retries <= 0:
                    raise GtpShutdown
        raise GtpTimeout('Timeout exceeded ({0})'.format(timeout))

    def _raw_send_command(self, command):
        """Encode, terminate and send a GTP command


        If raise_exceptions is False, the return value should be checked for
        success (True) or failure (False).

        Arguments:
        command -- a string containing the GTP command and any arguments
        raise_exceptions -- whether to raise GtpProcessError or return False
                           on OS errors (default True)
        """
        if self.gtp_debug:
            self._engerr(' Sending: {0}'.format(command))
        try:
            self.ein.write(command.rstrip().encode() + b'\n')
        except OSError as e:
            if self.show_debug:
                msg = 'Cannot send command to engine: {0}'
                raise GtpProcessError(msg.format(e)) from None
            else:
                return False
        if command.lower().strip() == 'quit':
            self.quit_sent = True
        return True

    def _engerr(self, message, **kwargs):
        """Write an error message, prefixed with the engine's name


        Arguments:
        message -- the message

        Keyword arguments are passed on to print_err.
        """
        name = self.name if hasattr(self, 'name') else '<undef>'
        outmsg = '[{0}] {1}'.format(name, str(message))
        print_err(outmsg, **kwargs)

    def set_err_file(self, filename=None):
        """Set self.err_file to a new file in a thread-safe manner

        This method acquires a lock, closes any previously opened err_file,
        opens the new one (for binary writing), and sets it be the new err_file
        before releasing the lock. To close the currently open err_file,
        (if any), call with no args.

        Arguments:

        filename -- file to open (Default None, which closes any open file)
        """
        if self.err_lock.acquire(blocking=True, timeout=1.5):
            if self.err_file:
                self.err_file.close()
            if filename:
                self.err_file = open(filename, 'wb')
            self.err_lock.release()
        else:
            msg = '[{0}] Could not acquire err_lock! Something is very wrong!'
            raise AllAbort(msg.format(self.name))

    def quit(self):
        """Send the quit command to the engine"""
        self.send_command('quit')

    def set_color(self, color):
        """Set the color for the engine (internal; produces no GTP)

        Arguments:
        color -- WHITE or BLACK
        """
        assert color in [BLACK, WHITE], 'Invalid color: {0}'.format(color)
        self.color = color
        if self.gtp_debug:
            self._engerr('* now playing as {0}'.format(color))

    def send_command(self, command, timeout=None):
        """Send a GTP command that produces no output.

        Arguments:
        commmand -- GTP command and its arguments, if any
        timeout -- seconds to wait before raising GtpTimeout
                   (default self.gtp_timeout)

        Exceptions: GtpTimeout, GtpIllegalMove, GtpResponseError
        """
        if timeout is None:
            timeout = self.gtp_timeout
        self._raw_send_command(command)
        try:
            response = self._raw_recv_response(timeout=timeout)
        except GtpTimeout:
            msg = '[{0}] GTP timeout({1}), command: {2}'
            raise GtpTimeout(msg.format(self.name, timeout, command)) from None
        if response.lower() == '? illegal move':
            msg = '[{0}] GTP engine protests: "{1}" (cmd: "{2}")'
            raise GtpIllegalMove(msg.format(self.name, response, command))
        if response != '=':
            msg = '[{0}] GTP unexpected response: "{1}" (cmd: "{2}")'
            raise GtpResponseError(msg.format(self.name, response, command))
        return True

    def get_response_for(self, command, timeout=None):
        """Send a GTP command and return its output

        Arguments:
        commmand -- GTP command and its arguments, if any
        timeout -- seconds to wait before raising GtpTimeout
                   (default self.gtp_timeout)

        Exceptions: GtpTimeout, GtpCannotScore, GtpResponseError

        """
        if timeout is None:
            timeout = self.gtp_timeout
        self._raw_send_command(command)
        try:
            response = self._raw_recv_response(timeout=timeout)
        except GtpTimeout:
            msg = '[{0}] GTP timeout({1}), command: {2}'
            raise GtpTimeout(msg.format(self.name, timeout, command)) from None
        if response.lower() == '? cannot score':
            msg = '[{0}] GTP scorer problem: "{1}" (cmd: "{2}")'
            raise GtpCannotScore(msg.format(self.name, response, command))
        if response[:2] != '= ':
            msg = '[{0}] GTP response error: "{1}" (cmd: "{2}")'
            raise GtpResponseError(msg.format(self.name, response, command))
        return response[2:]

    def clear_board(self):
        """Clear the engine's board"""
        self.send_command('clear_board')

    def time_left(self, period, count):
        """Send the GTP time_left command with the supplied arguments.

        Arguments:
        period -- time left/period length for Canadian/Japanese byo yomi
        count -- the number of stones/periods left for Canadian/Japanese b. y.
        """
        assert self.color in [BLACK, WHITE], \
                'Invalid color: {0}'.format(self.color)
        cmd = 'time_left {0} {1} {2}'
        self.send_command(cmd.format(self.color, period, count))

    def place_opponent_stone(self, coord):
        """Place a stone of the opponent's color on the engine's board.

        Arguments:
        coord -- the board coordinates in GTP notation

        Special exception: GtpIllegalMove
        """
        assert self.color in [BLACK, WHITE], \
                'Invalid color: {0}'.format(self.color)
        if self.color == BLACK:
            opp_color = WHITE
        else:
            opp_color = BLACK
        return self.send_command('play {0} {1}'.format(
                    opp_color, coord))

    def final_score(self):
        """Return the final score as assessed by the engine

        Special exception: GtpCannotScore
        """
        return self.get_response_for('final_score', timeout=self.gtp_scorer_to)

    def move(self, timeout):
        """Return a generated move from the engine (in GTP notation)

        Arguments:
        timeout -- max timeout before raising GtpTimeout (should be higher than
        time controls)
        """
        assert self.color in [BLACK, WHITE], \
                'Invalid color: {0}'.format(self.color)
        return self.get_response_for('genmove ' + self.color, timeout=timeout)

    def play_move_list(self, move_list, first_color=BLACK):
        """Place stones of alternating colors on the coordinates given in
        move_list

        Arguments:
        move_list -- list of strings containing board coordinates in GTP
                     notation
        first_color -- one of BLACK or WHITE: start with this color
                       (default BLACK)
        """
        color = first_color
        for move in move_list:
            if move.lower() == 'resign':
                continue
            self.send_command('play {0} {1}'.format(color, move))
            color = WHITE if color == BLACK else BLACK

    def score_from_move_list(self, move_list):
        """Returns engine's score for a game by placing all the stones first

        This calls the methods clear_board() and play_move_list(move_list) and
        returns final_score().

        Arguments:
        move_list -- list of strings containing board coordinates in GTP
                     notation
        """
        self.clear_board()
        self.play_move_list(move_list)
        return self.final_score()

    def game_setup(self, settings):
        """Send a number of GTP commands setting up game parameters

        Sets up board size, komi, time system and time settings. The Japanese
        byo yomi time system requires engine support of the GTP extension
        command kgs-time_settings

        Arguments:
        settings -- a GameSettings object containing the game settings
        """
        m = settings.main_time
        p = settings.period_time
        c = settings.period_count
        self.send_command('boardsize ' + str(settings.boardsize))
        self.send_command('komi ' + str(settings.komi))
        if settings.is_jpn_byo():
            cmd = 'kgs-time_settings byoyomi {0} {1} {2}'
            self.send_command(cmd.format(m, p, c))
        else:
            if settings.is_abs_time():
                p = 0  # GTP convention for abs time (=0)
            elif settings.is_untimed():
                p = 1  # GTP convention for no time sys (>0)
                c = 0  # GTP convention for no time sys (=0)
            self.send_command('time_settings {0} {1} {2}'.format(m, p, c))

    def verify_commands(self, command_set, show_diagnostics=False):
        # TODO return list of missing commands, let caller print diag
        """Verify engine supports commands, optionally print diagnostics

        An GtpMissingCommands exception is raised, if the engine does not pass

        Arguments:
        command_set -- a set of strings, the commands for which to check
        show_diagnostics -- print a diagnostic messages
        """
        known_cmds = set(self.get_response_for('list_commands').split())
        passed = True if known_cmds >= command_set else False
        if not passed or show_diagnostics:
            fmt_args = {}
            for cmd in ['name', 'version', 'protocol_version']:
                resp = self.get_response_for(cmd) \
                        if cmd in known_cmds else '<?>'
                fmt_args[cmd] = resp
            self._engerr(ENGINE_DIAG.format(**fmt_args)
                         + (ENGINE_OK if passed else ENGINE_FAIL))
        if not passed:
            missing_cmds = ', '.join(command_set - known_cmds)
            msg = '[{0}] missing required GTP commands:\n   {1}'
            raise GtpMissingCommands(msg.format(self.name, missing_cmds))


class TimedEngine(GtpEngine):
    """Add timekeeping and additional stats to GtpEngine
    """
    def __init__(self, name, settings=None, time_tolerance=0, move_wait=0,
                 **kwargs):
        """Init a TimedEngine

        Arguments:
        settings -- a GameSettings object containing the game settings (a new
                    one will be created, if it is not supplied)
        time_tolerance -- time tolerance in seconds (microsecond precision)
        move_wait -- time to wait between moves (seconds)
        **kwargs -- arguments to pass to GtpEngine __init__
        """
        super().__init__(name, **kwargs)
        self.settings = settings if settings else GameSettings()
        self.time_tol = time_tolerance
        self.move_wait = move_wait

    def _checkin_delta(self, delta):
        """Check in a new move, update engine timers, return whether time
         controls violated.


        Arguments:
        delta -- a timedate.delta object containing the move delta (the time
                 spent on the move)
        """
        stg = self.settings
        self.total_time_taken += delta
        if delta > self.max_time_taken:
            self.max_time_taken = delta

        # No time controls / no checking -- always return False (no violation)
        if stg.is_untimed() or self.time_tol < 0:
            return False

        # Absolute
        if stg.is_abs_time():
            time_left = self.main_time - self.total_time_taken.total_seconds()
            self.gtp_time_left = ((int(time_left) if time_left > 0 else 0), 0)
            next_move_timeout = time_left + self.time_tol
            self.move_timeout = next_move_timeout
            return next_move_timeout > 0

        # Not yet in byo yomi (but might fall through to byo yomi)
        if not self.in_byoyomi:
            main_left = stg.main_time - self.total_time_taken.total_seconds()
            if main_left > 0:
                self.gtp_time_left = (int(main_left), 0)
                if stg.is_jpn_byo():
                    additional = stg.period_time * stg.period_count
                else:
                    additional = stg.period_time
                self.move_timeout = main_left + additional + self.time_tol
                return False  # still in main time
            # starting byo yomi
            self.in_byoyomi = True
            delta = datetime.timedelta(seconds=(-main_left))

        # Japanese byo yomi
        if stg.is_jpn_byo():
            exhausted_periods = int(delta.total_seconds() / stg.period_time)
            if exhausted_periods >= self.periods_left:
                delta_with_tolerance = max(
                        0, delta.total_seconds() - self.time_tol)
                exhausted_periods = int(delta_with_tolerance / stg.period_time)
            self.periods_left -= exhausted_periods

            self.gtp_time_left = (stg.period_time, max(self.periods_left, 1))
            self.move_timeout = max(self.periods_left, 1) * stg.period_time \
                                + self.time_tol
            return self.periods_left <= 0

        # Canadian byo yomi
        if stg.is_cnd_byo():
            self.period_time_left -= delta.total_seconds()
            if self.period_time_left + self.time_tol < 0:
                violation = True
            else:
                violation = False
            self.stones_left -= 1
            if self.stones_left == 0:
                self.stones_left = stg.period_count
                self.period_time_left = stg.period_time
                self.gtp_time_left = (self.period_time_left, self.stones_left)
            else:
                self.gtp_time_left = (max(int(self.period_time_left), 0),
                                      self.stones_left)
            self.move_timeout = max(self.period_time_left, 0) \
                                + self.time_tol
            return violation

        return True  # don't know this time_sys; fail

    def _reset_game_timekeeping(self):
        """Reset timekeeping in preparation for a new game

        """
        s = self.settings
        self.max_time_taken = datetime.timedelta()
        self.total_time_taken = datetime.timedelta()
        self.periods_left = s.period_count if s.is_jpn_byo() else None
        self.stones_left = s.period_count if s.is_cnd_byo() else None
        self.period_time_left = s.period_time if s.is_cnd_byo() else None
        self.in_byoyomi = False

        # set initial GTP time left
        if not s.is_untimed():
            if s.main_time > 0:
                self.gtp_time_left = (s.main_time, 0)
            else:
                self.gtp_time_left = (s.period_time, s.period_count)
        else:
            self.gtp_time_left = None

        # set initial move timeout
        if not s.is_untimed():
            if s.is_cnd_byo():
                additional = s.period_time
            elif s.is_jpn_byo:
                additional = s.period_time * s.period_count
            else:
                additional = 0
            self.move_timeout = s.main_time + additional
        else:
            self.move_timeout = None

    def new_game(self, color):
        """Prepare for a new game: reset timekeeping, clear board, set color

        Argumetns:
        color -- WHITE or BLACK
        """
        self.clear_board()
        self._reset_game_timekeeping()
        self.set_color(color)
        self.moves_made = 0

    def timed_move(self):
        """Play a move and return a (coords, violation, delta) tuple

        The returned tuple contains move coordinates (GTP notation), whether
        the time controls (with tolerance) were violated (Booelan) and the
        move delta (time the engine used to think).
        """
        if self.time_tol >= 0 and not self.settings.is_untimed():
            self.time_left(*self.gtp_time_left)
            gtp_timeout = self.move_timeout + self.gtp_genmove_extra
        else:
            gtp_timeout = self.gtp_genmove_untimed_to
        before_move = datetime.datetime.utcnow()
        move = self.move(gtp_timeout)
        delta = datetime.datetime.utcnow() - before_move
        self.moves_made += 1  # increments on resign/timeout, unlike num_moves

        return(move, self._checkin_delta(delta), delta)


class ManagedEngine(TimedEngine):
    """Adds a context/resource manager to TimedEngine, builds from config.

    Main focus is on properly shutting down, killing sub-processes, closing
    file descriptors, etc.
     """
    def __init__(self, name, match, **kwargs):
        """Inits a Managed Engine

        Arguments
        name -- name of the engine
        match -- the match where the engine will play
        """
        super().__init__(name,
                         settings=match.game_settings,
                         time_tolerance=match.time_tol,
                         move_wait=match.move_wait,
                         **kwargs)
        self.last_restart_rq = None
        self.popen = None
        self.restarts = 0
        self.cmd_line = match.cnf[name]['cmd']
        self.wk_dir = match.cnf[name].get('wkdir', fallback=None)
        self.req_cmds = set()
        if self.name in match.engine_names:
            self.req_cmds |= match.req_commands
        if self.name == match.scorer_name:
            self.req_cmds |= match.req_cmd_scorer

        self.show_diagnostics = match.show_diagnostics
        self.show_debug = match.show_debug
        self.gtp_debug = match.gtp_debug
        self.suppress_err = match.cnf[name].getboolean(
                    'quiet', fallback=match.suppress_err)
        self.log_stderr = match.cnf[name].getboolean(
                    'log_stderr', fallback=match.log_stderr)
        self.match_dir = match.created_match_dir
        self.stats = [0] * 8

    def __enter__(self):
        """Enters ManagedEngine context

        """
        if self.show_debug:
            self._engerr('Entering context [{0}]'.format(self.name))

        while True:
            try:
                self._invoke()
                break
            except (GtpMissingCommands, GtpResponseError) as e:
                msg = '[{0}] Permanent engine problem:\n{1}'
                raise PermanentEngineError(self.name, msg.format(self.name, e))
            except GtpException:
                self.restart()
        return self

    def __exit__(self, et, ev, trace):
        """Exits ManagedEngine context, calls shutdown() and closes stderr log

        """
        if self.show_debug:
            self._engerr('Exiting context (Err: {0}, {1}).'.format(et, ev))
        self.shutdown()
        self.set_err_file()

    def _cmd_line_interpolate(self):
        return self.cmd_line.format(
                    name=self.name,
                    matchdir=os.path.abspath(self.match_dir),
                    boardsize=self.settings.boardsize,
                    komi=self.settings.komi,
                    maintime=self.settings.main_time,
                    periodtime=self.settings.period_time,
                    periodcount=self.settings.period_count,
                    timesys=self.settings.time_sys)

    def _invoke(self, is_restart=False):
        """Invokes the subproccess and starts reader threads

        Arguments:
        is_restart -- skip some diagnostic messages (default False)

        """
        if self.popen:
            return
        cmd_line_interp = self._cmd_line_interpolate()
        if self.show_diagnostics and not is_restart:
            self._engerr(ENGINE_DIR.format(dir=self.wk_dir))
            self._engerr(ENGINE_CMD.format(cmd=cmd_line_interp))

        # change to wk_dir, if supplied
        # (do not use popen's cwd, as behaviour platform-dependant)
        if self.wk_dir:
            try:
                starting_wk_dir = os.getcwd()
                os.chdir(self.wk_dir)
            except OSError as e:
                raise PermanentEngineError(self.name, str(e))
        windows = sys.platform.startswith('win')
        if (windows):
            platform_cmd = cmd_line_interp
        else:
            platform_cmd = shlex.split(cmd_line_interp)
        try:
            self.popen = subprocess.Popen(
                        platform_cmd,
                        bufsize=0,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        except OSError as e:
            msg = '[{0}] Could not run command:\n{1}\ncmd: {2}\ndir: {3}'
            raise PermanentEngineError(
                    self.name,
                    msg.format(
                            self.name, e,
                            platform_cmd, os.getcwd())) from None
        if self.wk_dir:
            os.chdir(starting_wk_dir)
        self.eout = self.popen.stdout
        self.ein = self.popen.stdin
        self.eerr = self.popen.stderr
        self._threads_init()
        self.verify_commands(self.req_cmds, self.show_diagnostics)

    def shutdown(self):
        """Shutdown engine, take care of subprocess, threads, fds.
        """
        if not self.popen:
            self._engerr('Shutdown: nothing to shut down.')
            return
        if self.show_debug:
            self._engerr('Shutting down.')
        if not self.quit_sent:
            if self.show_debug:
                self._engerr('Engine was not quit, sending "quit"')
            try:
                self.quit()
            except (GtpTimeout, GtpProcessError, GtpShutdown):
                self._engerr('Sending "quit" failed')
        if self.show_debug:
            self._engerr('Waiting for process (max {0}s)'.format(WAIT_QUIT))
        try:
            self.popen.wait(WAIT_QUIT)
        except subprocess.TimeoutExpired as e:
            self._engerr('Killing process: ({0})'.format(e))
            self.popen.kill()

        self._threads_join()
        self.popen.stdout.close()
        self.popen.stderr.close()
        self.popen.stdin.close()
        self.popen.wait()
        poll = self.popen.poll()
        if poll is None:
            msg = '[{0}] Somehow, shutdown seems to have failed.'
            raise AllAbort(msg.format(self.name))
        self.popen = None
        msg = 'Shutdown successful (exit code = {0}).'
        self._engerr(msg.format(poll))

    def restart(self, severity=1):
        """Restart the engine up to ENGINE_RESTART times

        Arguments:
        severity -- by how much to increment the restart counter which is
                    checked against ENGINE_RESTART, a higher number leads to
                    fewer restarts--useful for some error that are not worth
                    doing many restarts over
        """

        self._engerr('Restarting...')
        utcnow = datetime.datetime.utcnow()
        if self.last_restart_rq:
            s_since_last = (utcnow - self.last_restart_rq).total_seconds()
            if s_since_last < 2:
                msg = 'Restarting too often, too fast, about to give up.'
                self._engerr(msg)
                severity += 2
            elif s_since_last < 10:
                msg = 'Restarting fairly often, will give up soon.'
                self._engerr(msg)
                severity += 1
            elif s_since_last > 600:  # 10 min running without problem
                self.restarts = max(ENGINE_RESTART // 2, self.restarts)
            elif s_since_last > 1800:  # 30 min
                self.restarts = ENGINE_RESTART
        self.last_restart_rq = utcnow

        self.restarts += severity
        if self.restarts > ENGINE_RESTART:
            msg = ('Engine {0} restarted too quickly too many times'
                   ' (or with high severity level).')
            raise PermanentEngineError(
                        self.name, msg.format(self.name, ENGINE_RESTART))
        self.shutdown()
        try:
            self._invoke(is_restart=True)
        except GtpException:
            self.restart()

    def add_game_result_to_stats(self, game):
        """Update engine stats with the game result supplied in game

        Arguments:
        game -- a Game object containing the game result
        """
        assert self.color in [BLACK, WHITE], \
                'Invalid color: {0}'.format(self.color)

        # update games won/totals:
        self.stats[1] += 1  # total games
        if self.color == WHITE:
            self.stats[3] += 1  # total as W
            if game.winner == WHITE:
                self.stats[0] += 1  # total wins
                self.stats[2] += 1  # wins as W
        else:  # self is BLACK
            self.stats[5] += 1  # total as B
            if game.winner == BLACK:
                self.stats[0] += 1  # total wins
                self.stats[4] += 1  # wins as B

        maxtt = self.max_time_taken.total_seconds()
        if maxtt > self.stats[6]:
            self.stats[6] = maxtt  # max t/move for match
        self.stats[7] += self.total_time_taken.total_seconds()

    def print_match_stats(self):
        """Prints some match stats to stderr
        """
        self._engerr(ENGINE_MSTA.format(stats=self.stats))


class Match:
    """Plays whole matches, stores settings, manages context

    Context manager managing ManagedEngine instances, the match logfile, and
    the directories needed (match dir, stderr, SGFs). GTP engines are not
    created/invoked before the context of a Match is entered. This class
    ensures (together with ManagedEngine) that all engines are terminated
    normally or, failing that, killed off before starting another match. If
    this somehow fails, AllAbort is called, cancelling all further Matches,
    since a system with processes running wild is likely to prouce skewed match
    results.
    """
    def __init__(self, section_name, cnf, blacklist):
        """Initializes a Match from DumbarbConfig and a match section name

        Arguments:
        section_name -- the match name, name of a section in the config file(s)
        cnf -- DumbarbConfig instance containing the configuration
        """
        # set when entering context
        self.estack = None
        self.engines = None
        self.scorer = None
        self.out_stream = None
        self.mt_stream = None
        self.created_match_dir = None

        # config
        self.cnf = cnf
        section = cnf[section_name]
        sname_elems = section_name.split()
        for elm in sname_elems:
            if not self._chk_name(elm):
                raise ConfigError(ENGINE_BNAM.format(badname=elm))
        try:
            self.engine_names = sname_elems[:2]
            # abort on blacklisted engines
            bad_engines = set(self.engine_names) & blacklist
            if (bad_engines):
                msg = 'Skipping match with blacklisted engine(s): {0}'
                raise MatchAbort(msg.format(', '.join(bad_engines)))
            # GameSettings object
            self.game_settings = GameSettings(
                        boardsize=int(section.get('boardsize', 19)),
                        komi=float(section.get('komi', 7.5)),
                        main_time=int(section.get('maintime', 0)),
                        period_time=int(section.get('periodtime', 2)),
                        period_count=int(section.get('periodcount', 0)),
                        time_sys=int(section.get('timesys', 2)))

            # other config values
            self.name = ' '.join(sname_elems)
            usc_name = '_'.join(sname_elems)
            self.log_basename = usc_name + '.log'
            self.mt_log_basename = usc_name + '.mvtimes'
            self.unchecked_match_dir = usc_name
            self.num_games = int(section.get('numgames', 100))
            self.consec_passes_to_end = int(
                    section.get('consecutivepasses', 2))
            self.match_wait = float(section.get('matchwait', 1))
            self.game_wait = float(section.get('gamewait', 0.5))
            self.move_wait = float(section.get('movewait', 0))
            self.time_tol = float(section.get('timetolerance', 0))
            self.scorer_name = section.get('scorer', None)
            self.disable_sgf = section.getboolean('disablesgf', False)
            self.enforce_time = section.getboolean('enforcetime', False)
            self.suppress_err = section.getboolean('quiet', False)
            self.log_stderr = section.getboolean('logstderr', True)

            self.gtp_timeout = float(section.get('gtptimeout', 3))
            self.gtp_scorer_to = float(section.get('gtpscorerto', 4))
            self.gtp_genmove_extra = float(section.get('gtpgenmoveextra', 15))
            self.gtp_genmove_untimed_to = float(
                    section.get('gtpgenmoveuntimedto', 60))

        except ValueError as e:
            msg = 'Config value error for match [{0}]: {1}'
            raise ConfigError(msg.format(section.name, e))

        # set of GTP commands engines are required to support
        self.req_commands = {'boardsize', 'komi', 'genmove', 'play',
                             'clear_board', 'quit'}
        if self.game_settings.time_sys > 0:
            self.req_commands.add('time_left')
        if self.game_settings.time_sys == 3:
            self.req_commands.add('kgs-time_settings')
        else:
            self.req_commands.add('time_settings')

        # set of GTP commands a scorer engine would be required to support
        self.req_cmd_scorer = (self.req_commands | {'final_score'}) \
                              - {'genmove', 'time_left'}

        # from args
        self.start_with = cnf.start_with
        self.show_diagnostics = cnf.show_diagnostics
        self.show_debug = cnf.show_debug
        self.show_progress = cnf.show_progress
        self.gtp_debug = cnf.gtp_debug

        # field widths for formatting output
        self.max_dgts = len(str(self.num_games))
        self.n_width = max(
                len(self.engine_names[0]), len(self.engine_names[1]),
                len(RESULT_JIGO), len(RESULT_NONE), len(RESULT_OERR))

    def __enter__(self):
        """Make directories, create engines, open logfiles, put on ExitStack

        """
        if self.show_diagnostics:
            print_err('============ match {0} ============'.format(self.name))
        self.created_match_dir = self._mk_match_dir()
        self.estack = contextlib.ExitStack()

        # start engines
        timeouts = {'gtp_timeout': self.gtp_timeout,
                    'gtp_scorer_to': self.gtp_scorer_to,
                    'gtp_genmove_extra': self.gtp_genmove_extra,
                    'gtp_genmove_untimed_to' : self.gtp_genmove_untimed_to}

        self.engines = [self.estack.enter_context(ManagedEngine(name, self,
                                                                **timeouts))
                        for name in self.engine_names]

        # create scorer as separate ManagedEngine, if necessary
        if self.scorer_name:
            try:
                i = self.engine_names.index(self.scorer_name)
                self.scorer = self.engines[i]
            except ValueError:
                self.scorer = self.estack.enter_context(
                            ManagedEngine(self.scorer_name, self))

        # match subdirs
        if not self.disable_sgf:
            self.created_sgf_dir = self._mk_sub(SGF_SUBDIR)
        create_err_dir = False
        for engine in self.engines:
            if engine.log_stderr:
                create_err_dir = True
                break
        if create_err_dir:
            self.created_err_dir = self._mk_sub(ERR_SUBDIR)

        # results log & move times log
        log_file = os.path.join(self.created_match_dir, self.log_basename)
        mt_log_file = os.path.join(
                self.created_match_dir, self.mt_log_basename)
        self.out_stream = self.estack.enter_context(open(log_file, 'w'))
        self.mt_stream = self.estack.enter_context(open(mt_log_file, 'w'))
        return self

    def __exit__(self, et, ev, trace):
        """Close the ExitStack (ManagedEngines, open logfile)

        """
        if self.show_debug:
            msg = 'Closing exit stack: {0} (Err: {1}: {2})'
            etname = et.__name__ if et else None
            print_err(msg.format(self.name, etname, ev))
        self.estack.close()
        return False

    def _mk_match_dir(self):
        """Make & return match dir, append -001, -002, etc. if it exists

        """
        try_dir = self.unchecked_match_dir
        if os.path.exists(try_dir):
            for i in range(1, 999):
                try_dir = self.unchecked_match_dir + '-{0:03}'.format(i)
                if not os.path.exists(try_dir):
                    msg = '"{0}" already exists; storing log/SGFs in "{1}"'
                    print_err(msg.format(self.unchecked_match_dir, try_dir))
                    break
        try:
            os.mkdir(try_dir)
        except OSError as e:
            msg = 'Could not create results directory "{0}":\n    {1}'
            raise PermanentEngineError(msg.format(try_dir, e)) from None
        return try_dir

    def _mk_sub(self, subdir):
        """Make a subdir in the match dir, return its name

        Arguments:
        subdir -- the directory to create and return
        """
        dir_name = os.path.join(self.created_match_dir, subdir)
        os.mkdir(dir_name)
        return dir_name

    def _print_indicator(self, game_num):
        """Print a character indicating a game has been finished


        A dot is printed by default, the tens digit of game_num every ten
        games, and a newline every 100.

        Arguments:
        game_num -- the game number for which to print an indicator
        """
        if not self.show_progress:
            return
        char = str(game_num)[-2:-1] if game_num % 10 == 0 else '.'
        end = '\n' if game_num % 100 == 0 else ''
        print_err(char + end, skipformat=True)

    def _output(self, string, flush=False, log='result'):
        """Write to the output stream, optionally flush


        Arguments:
        string -- string to write
        flush -- whether to flush (default False)

        """
        log_streams = {
                'result': self.out_stream,
                'movetimes': self.mt_stream}
        stream = log_streams[log]
        stream.write(string)
        if flush:
            stream.flush()

    def _output_move_times(self, game_num, game):
        times = [FMT_MVTIME.format(move=str(m), time=str(t))
                 for m, t in zip(game.move_list, game.move_times)]
        entry = FMT_MTENTRY.format(seqno=game_num,
                                   swidth=self.max_dgts,
                                   mvs=' '.join(times))
        self._output(entry, log='movetimes', flush=True)

    def _output_result(self, game_num, game):
        """Write a result line to the output stream


        Arguments:
        game_num -- game number
        game -- Game object of a finished game

        """
        # print pre-result string
        iso_date = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        self._output(FMT_PRE_RES.format(
                    stamp=iso_date, seqno=game_num,
                    swidth=self.max_dgts, nwidth=self.n_width,
                    name1=self.engines[0].name, col1=self.engines[0].color,
                    name2=self.engines[1].name, col2=self.engines[1].color))

        # get/caluclate engine time stats
        eng_stats = []
        for engine in self.engines:
            if engine.moves_made > 0:
                avgtt = (engine.total_time_taken.total_seconds()
                         / engine.moves_made)
            else:
                avgtt = 0
            eng_stats.append({
                            'name': engine.name,
                            'maxtt': engine.max_time_taken.total_seconds(),
                            'tottt': engine.total_time_taken.total_seconds(),
                            'avgtt': avgtt,
                            'moves': engine.moves_made})

        # print result, time stats, move count, time violators string
        if game.winner == WHITE:
            self._output(FMT_WIN_W.format(
                        name=game.white_engine.name, nwidth=self.n_width))
        elif game.winner == BLACK:
            self._output(FMT_WIN_B.format(
                        name=game.black_engine.name, nwidth=self.n_width))
        else:
            self._output(FMT_ALT_RES.format(
                        result=game.winner, nwidth=self.n_width))
        self._output(FMT_REST.format(
                    name1=eng_stats[0]['name'],
                    maxtt1=eng_stats[0]['maxtt'],
                    tottt1=eng_stats[0]['tottt'],
                    avgtt1=eng_stats[0]['avgtt'],
                    name2=eng_stats[1]['name'],
                    maxtt2=eng_stats[1]['maxtt'],
                    tottt2=eng_stats[1]['tottt'],
                    avgtt2=eng_stats[1]['avgtt'],
                    mv1=eng_stats[0]['moves'],
                    mv2=eng_stats[1]['moves'],
                    moves=game.num_moves,
                    reason=game.win_reason,
                    vio=game.time_vio_str if game.time_vio_str else VIO_NONE,
                    nwidth=self.n_width),
                flush=True)

    @staticmethod
    def _chk_name(name):
        """Check if name follows the rules

        """
        try:
            return name[0] in ENGALW_FRST and len(name) <= ENGALW_MAXC \
                        and set(name) <= set(ENGALW_CHAR) and name[-1:] != '.'
        except ValueError:
            pass
        return False

    def _print_match_stats(self):
        """Print overall match stats, calling engines' print_match_stats()

        """
        if self.show_progress and not self.num_games % 100 == 0:
            print_err(prefix='')
        print_err('Match ended. Overall stats:')
        for engine in self.engines:
            engine.print_match_stats()

    def _write_SGF(self, game_num, game):
        if self.disable_sgf:
            return
        sgf_file = FN_FORMAT.format(num=game_num, ext='sgf')
        sgf_wr = SgfWriter(
                        self.game_settings,
                        game.white_engine.name, game.black_engine.name,
                        'game {0}'.format(game_num),
                        'dumbarb {0}-game match'.format(self.num_games))
        sgf_wr.add_move_list(game.move_list, game.move_times)
        sgf_wr.set_result(game.winner, game.win_reason)
        sgf_wr.write_file(sgf_file, self.created_sgf_dir)
        pass

    def play(self):
        """Play the match, handle result & stderr logging, SGF
        """

        # check start_with is valid
        if self.start_with > self.num_games:
            msg = ('Cannot start with game {0}'
                   'when the whole match is {1} games')
            raise MatchAbort(msg.format(self.start_with, self.num_games))

        # set of all engines running for this game
        all_engines = set(self.engines)
        if self.scorer:
            all_engines.add(self.scorer)

        # board settings
        for engine in all_engines:
            while True:
                try:
                    engine.game_setup(self.game_settings)
                    break
                except GtpException:
                    engine.restart()  # will raise MatchAbort after several

        # match wait
        if self.match_wait:
            time.sleep(self.match_wait)

        # match loop
        if self.start_with & 1:
            white, black = self.engines
        else:
            black, white = self.engines
        for game_num in range(self.start_with, self.num_games + 1):
            if self.game_wait:
                time.sleep(self.game_wait)
            for engine in all_engines:
                if engine.log_stderr:
                    fname = FN_FORMAT.format(
                                num=game_num, ext=engine.name + '.log')
                    engine.set_err_file(
                                os.path.join(self.created_err_dir, fname))
            game = Game(white, black, self)
            game.play()
            self._output_result(game_num, game)
            self._output_move_times(game_num, game)
            self._write_SGF(game_num, game)
            for engine in self.engines:
                engine.add_game_result_to_stats(game)
            self._print_indicator(game_num)
            white, black = black, white

        # match end: print stats
        self._print_match_stats()


class Game:
    """Plays games, scores them, and contains the game result & stats. """
    GTP_LETTERS = string.ascii_lowercase.replace('i', '')

    def __init__(self, white_engine, black_engine, match):
        """Initialize a Game object

        Arguments:
        white_engine - a ManagedEngine to play as W
        black_engine - a ManagedEngine to play as B
        match - the Match to which the game belongs
        """
        self.white_engine = white_engine
        self.black_engine = black_engine
        self.match = match
        self.winner = None
        self.win_reason = None
        self.num_moves = 0
        self.time_vio_str = None
        self.move_list = []
        self.move_times = []

    def _score_game(self):
        """Return (winner, win_reason) as calculated by scorer


        Example return tuples: (WHITE, 5.5), (RESULT_JIGO, REASON_JIGO)
        Returns (RESULT_NONE, REASON_NONE) if match has no scorer assigned or
        if there was a problem.
        """
        scr = self.match.scorer
        if scr:
            try:
                if scr is self.white_engine or scr is self.black_engine:
                    score = scr.final_score()
                else:
                    score = scr.score_from_move_list(self.move_list)
            except GtpCannotScore as e:
                msg = 'Could not score game. Refusal from {0}:'
                print_err(msg.format(scr.name), sub=e)
                return RESULT_NONE, REASON_SCOR
            except GtpException as e:
                msg = 'Could not score game. GTP error from {0}:'
                print_err(msg.format(scr.name), sub=e)
                scr.restart()
                # leaving this game be, maybe scorer will score others?
                return RESULT_NONE, REASON_SCOR
            try:
                if score[0] == '0':
                    return RESULT_JIGO, REASON_JIGO
                if score[0] in [BLACK, WHITE] and score[1] == '+':
                    return score[0], score[2:]
            except IndexError:
                    pass
            msg = '\n_could not score game. Bad score format from {0}:'
            print_err(msg.format(scr.name), sub=score)
            return RESULT_NONE, REASON_SCOR
        return RESULT_NONE, REASON_NONE

    def _prepare_engines(self):
        coleng = {WHITE: self.white_engine, BLACK: self.black_engine}
        for (col, eng) in coleng.items():
            while True:
                try:
                    eng.new_game(col)
                    break
                except GtpException:
                    eng.restart()  # will abort match after several tries

    def is_move(self, move):
        """Syntax check move, return True if OK

        Arguments:
            move -- move in GTP notation (without color)
        """
        move_low = move.lower()
        if move_low in ['pass', 'resign']:
            return True
        try:
            x = self.GTP_LETTERS.index(move_low[0]) + 1
            y = int(move_low[1:])
            for coord in (x, y):
                if coord < 1 or coord > self.match.game_settings.boardsize:
                    return False
            return True
        except (ValueError, IndexError):
            return False

    def play(self):
        """Run the game, set winner, move_list, time_vio_str and other attribs
        """
        assert not (self.winner or self.win_reason or self.time_vio_str
                    or self.move_list or self.num_moves)
        consec_passes = 0
        self._prepare_engines()
        mover = self.black_engine  # mover moves; start with black
        placer = self.white_engine  # placer places move generated by mover
        while True:
            if mover.move_wait:
                time.sleep(mover.move_wait)
            try:
                (move, is_time_violation, delta) = mover.timed_move()
            except GtpException as e:  # TODO distinguish diff GTP exceptions
                msg = 'GTP error with {0}:'
                print_err(msg.format(mover.name), sub=e)
                mover.restart()  # has a limit, so we won't hang
                self.winner, self.win_reason = RESULT_OERR, REASON_OERR
                return

            # move check
            if not self.is_move(move):
                msg = ('[{0}] Generated move has bad syntax or is outside'
                       ' board:\n   {1}')
                raise PermanentEngineError(
                            mover.name, msg.format(mover.name, move))

            self.move_list.append(move)
            self.move_times.append(delta.total_seconds())

            # end game if time exceeded and enforce_time=1, only log otherwise
            if is_time_violation:
                violator = '{name} {m}[{s}]'.format(
                            name=mover.name,
                            m=self.num_moves + 1,
                            s=delta.total_seconds())
                if not self.time_vio_str:
                    self.time_vio_str = violator
                else:
                    self.time_vio_str += ', ' + violator
                if self.match.enforce_time:
                    self.winner, self.win_reason = placer.color, REASON_TIME
                    return

            # end game if resigned
            if move.lower() == 'resign':
                self.winner, self.win_reason = placer.color, REASON_RESIGN
                return

            # move is not resign or invalidated by time controls enforcement
            self.num_moves += 1

            #  passes / try to score game if consecutive passes > config val
            consec_passes = consec_passes + 1 if move.lower() == 'pass' else 0
            if consec_passes >= self.match.consec_passes_to_end:
                self.winner, self.win_reason = self._score_game()
                return

            # place move on opponent board
            try:
                placer.place_opponent_stone(move)
            except GtpIllegalMove as e:
                self.winner, self.win_reason = RESULT_UFIN, REASON_ILMV
                msg = 'Match {0}: {1} does not like a move'
                print_err(msg.format(self.match.name, placer.name), sub=e)
                return
            except GtpException as e:
                msg = 'GTP error with {0}'
                print_err(msg.format(placer.name), sub=e)
                placer.restart()
                # few more tries
                self.winner, self.win_reason = RESULT_OERR, REASON_OERR
                return

            mover, placer = placer, mover


class DumbarbConfig:
    """Reads in the config file and provides access to config values. """
    def __init__(self):
        """Initialize object containing all the config values

        Use argparse to read command line parameters, including config
        file(s), then parse the config files as well.
        """
        args = self._parse_args()

        self.config = configparser.ConfigParser(
                    inline_comment_prefixes='#',
                    empty_lines_in_values=False)
        self.config.SECTCRE = re.compile(r'\[ *(?P<header>[^]]+?) *\]')
        try:
            read_files = self.config.read(args.config_file)
        except configparser.Error as e:
            msg = 'Problem reading config file(s): {0}'
            raise ConfigError(msg.format(e))

        sections = self.config.sections()
        self.match_sections = [x for x in sections
                               if ' ' in x and not x.startswith('$')]
        self.engine_sections = [x for x in sections
                                if ' ' not in x and not x.startswith('$')]
        if not self.match_sections:
            msg = 'No match sections found in config file(s):\n   {0}'
            raise ConfigError(msg.format(', '.join(args.config_file)))
        for sec in self.config.keys():
            keys = self.config[sec].keys()
            if not keys <= INI_KEYSET:
                msg = 'Invalid keyword(s) in config file(s):\n   {0}'
                raise ConfigError(msg.format(', '.join(keys - INI_KEYSET)))
        self.start_with = args.start_with
        self.show_diagnostics = not args.quiet
        self.show_debug = args.debug
        self.show_progress = not args.quiet and not args.no_indicator
        self.gtp_debug = args.gtp_debug

    def __getitem__(self, key):
        """Provide access to config file sections (engine/match defs) """
        try:
            key = self.config[key]
        except KeyError as e:
            msg = 'Could not find section for engine {0}'
            raise ConfigError(msg.format(e)) from None
        return key

    @staticmethod
    def _parse_args():
        """Parse command line arguments and return an ArgumentParser

        """
        blurb = '''
        Copyright (C) 2017 Stanislav Traykov
        License: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
        This is free software: you are free to change and redistribute it.
        There is NO WARRANTY, to the extent permitted by law.
        '''
        arg_parser = argparse.ArgumentParser(
                    description='Run matches between GTP engines.',
                    formatter_class=argparse.RawDescriptionHelpFormatter)
        arg_parser.add_argument(
                    'config_file',
                    nargs='+',
                    metavar='<config file>',
                    type=str,
                    help='Configuration file')
        arg_parser.add_argument(
                    '-I', '--no-indicator',
                    action='store_true',
                    help='Disable progress indicator')
        arg_parser.add_argument(
                    '-n', '--start-with',
                    metavar='<start no>',
                    type=int, default=1,
                    help='Start with this game number (default 1)')
        arg_parser.add_argument(
                    '-q', '--quiet',
                    action='store_true',
                    help='Quiet mode: nothing except critical messages')
        arg_parser.add_argument(
                    '-d', '--debug',
                    action='store_true',
                    help='Show extra diagnostics')
        arg_parser.add_argument(
                    '-g', '--gtp-debug',
                    action='store_true',
                    help='Show GTP commands/responses')
        arg_parser.add_argument(
                    '-c', '--continue',
                    action='store_true',
                    help='Continue an interrupted session')
        arg_parser.add_argument(
                    '-v', '--version',
                    action='version',
                    version='{0} {1}\n{2}'.format(
                                DUMBARB, DUMBVER, textwrap.dedent(blurb)))
        return arg_parser.parse_args()


def print_err(message='', end='\n', flush=True, prefix='<ARB> ',
              sub=None, skipformat=False):
    """Print a message to stderr, thread-safe and magic-performing

    If the last thing printed did not have a newline (e.g. indicator dot),
    print_err will prepend a newline.

    Arguments:
    message -- the message to print (default '')
    end -- an optional termination string (default '\n')
    flush -- whether to flush the buffer (default True)
    prefix -- prefix messages with this (default '<ARB> ')
    sub -- secondary message that will be specially indented (default None)
    skipformat -- skip formatting magic; no end, no prefix (default False)
    """
    if not hasattr(print_err, 'global_lock'):
        print_err.global_lock = threading.Lock()
        print_err.last_print_nl = True
    s_end = '' if skipformat else str(end)
    s_prefix = '' if skipformat else str(prefix)
    if sub is None:
        s_sub = ''
    else:
        s_sub = '\n' + textwrap.indent(str(sub).rstrip(), str(prefix) + '   ')
    with print_err.global_lock:
        prepend = '' if skipformat or print_err.last_print_nl else '\n'
        outmessage = prepend + s_prefix + str(message) + s_sub + s_end
        print_err.last_print_nl = outmessage.endswith('\n')
        sys.stderr.write(outmessage)
        if flush:
            sys.stderr.flush()


if __name__ == '__main__':
    blacklist = set()  # engines with permanent errors
    try:
        cnf = DumbarbConfig()
    except ConfigError as e:
        print_err('Config error:', sub=e)
        sys.exit(125)

    aborted = 0
    for s in cnf.match_sections:
        if s.startswith('$') or s.lower().startswith('skip '):
            continue
        try:
            with Match(s, cnf, blacklist=blacklist) as m:
                m.play()
        except (ConfigError, GtpException, MatchAbort,
                OSError, ValueError) as e:
            msg = 'Match [{0}] aborted ({1}):'
            print_err(msg.format(s, e.__class__.__name__), sub=e)
            if type(e) == PermanentEngineError:
                print_err('Blacklisting engine from further matches.')
                blacklist.add(e.engine_name)
            if cnf.show_debug:
                trfmt = traceback.format_exception(*sys.exc_info())
                print_err(sub=''.join(trfmt))
            aborted += 1
            continue
        except AllAbort as e:
            print_err('Something bad happened. Aborting all matches.', sub=e)
            exit(124)

    sys.exit(max(120, aborted))
