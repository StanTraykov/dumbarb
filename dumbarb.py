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

import os, sys, traceback
import contextlib, subprocess, threading, queue
import datetime, re, time, shlex, string, textwrap
import argparse, configparser

#################################### CONFIG ####################################

DUMBARB = 'dumbarb'
DUMBVER = '0.3.0'

# results format

FMT_PRE_RES = '{stamp} [{seqno:0{swidth}}] {name1} {col1} {name2} {col2} = '
FMT_WIN_W   = '{name:>{nwidth}} W+'
FMT_WIN_B   = '{name:>{nwidth}} B+'
FMT_ALT_RES = '{result:>{nwidth}}   '
FMT_REST    = ('{reason:6} {moves:3} {mv1:3} {mv2:3}'
            ' {tottt1:11.6f} {avgtt1:9.6f} {maxtt1:9.6f}'
            ' {tottt2:11.6f} {avgtt2:9.6f} {maxtt2:9.6f} VIO: {vio}\n')

RESULT_JIGO = 'Jigo' # a.k.a. draw
RESULT_NONE = 'None' # ended with passes but couldn't/wasn't instructed to score
RESULT_UFIN = 'UFIN' # game interrupted (illegal move?)
RESULT_ERR  = 'ERR'  # some error occured


REASON_ILM  = 'IL' # one of the engines didn't like a move
REASON_JIGO = '==' # jigo
REASON_NONE = 'XX' # scoring was not requeted
REASON_SCOR = 'SD' # scorer problem
REASON_ERR  = 'EE' # some error occured

VIO_NONE    = 'None'

# filename format for SGF and other game-specific files

FN_FORMAT   = 'game_{num}.{ext}'

# timeouts when receiving data via pipe from a GTP process

GTP_TIMEOUT = 2.0  # timeout for GTP commands in seconds
GTP_SCO_TIM = 6.0  # timeout for GTP final_score in seconds (for scorer engine)
GTP_GMT_NON = 60   # GTP genmove timeout when no time keeping by engine
GTP_GMT_EXT = 10   # GTP genmove timeout: extra seconds to add to control time
                   # (this is for when to start terminating/killing the process)

# SGF

SGF_AP_VER  = DUMBARB + ':' + DUMBVER
SGF_BEGIN   = ('(;GM[1]FF[4]CA[UTF-8]AP[{0}]RU[{1}]SZ[{2}]KM[{3}]GN[{4}]'
                'PW[{5}]PB[{6}]DT[{7}]EV[{8}]RE[{9}]\n')
SGF_MOVE    = ';{0}[{1}{2}]\n'
SGF_END     = ')\n'
SGF_SUBDIR  = 'SGFs'

# stderr logging

ERR_SUBDIR  = 'stderr'

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
ENGINE_DIR  = 'dir: {dir}'
ENGINE_CMD  = 'cmd: {cmd}'
ENGINE_DIAG = '**** {name} version {version}, speaking GTP {protocol_version}'
ENGINE_OK   = ' - OK'
ENGINE_FAIL = ' - FAIL'
ENGINE_MSTA = '{stats[1]} ({stats[3]} W, {stats[5]} B); ' \
                    '{stats[0]} won ({stats[2]} W, {stats[4]} B); ' \
                    'max: {stats[6]:.2f}s, tot: {stats[7]:.0f}s'

# process communication settings

WAIT_QUIT   = 1      # seconds to wait for engine to exit before killing process
Q_TIMEOUT   = 0.5    # seconds to block at a time when waiting for response

################################## NON-CONFIG ##################################
# Do not change

REASON_RESIGN = 'Resign' # } used to produce proper SGF
REASON_TIME   = 'Time'   # }
BLACK = 'B' # } GTP and other stuff rely on these values
WHITE = 'W' # }

INI_KEYSET = {'cmd', 'wkdir', 'pregame', 'prematch', 'postgame', 'postmatch',
              'quiet', 'logstderr',
              'boardsize', 'komi', 'maintime', 'periodtime', 'periodcount',
              'timesys', 'timetolerance', 'enforcetime',
              'movewait', 'matchwait', 'gamewait',
              'numgames', 'scorer', 'consecutivepasses', 'disablesgf'}

################################## exceptions ##################################

class GtpException(Exception):
    """ Parent class for GTP exceptions """
    pass

class GtpMissingCommands(GtpException):
    """ Engine does not support the required command set for its function """
    pass

class GtpResponseError(GtpException):
    """ Engine sent an invalid / unexpected response """
    pass

class GtpIllegalMove(GtpResponseError):
    """ Engine replied with '? illegal move' """
    pass

class GtpCannotScore(GtpResponseError):
    """ Engine replied with '? cannot score' """
    pass

class GtpProcessError(GtpException):
    """ The interprocess communication with the engine failed """
    pass

class GtpTimeout(GtpException):
    """ Engine timed out """
    pass

class GtpShutdown(GtpException):
    """ Engine is being shut down """
    pass

class ConfigError(Exception):
    """ Parsing, value or other error in config """
    pass

class MatchAbort(Exception):
    """ Match needs to be aborted """
    pass

class AllAbort(Exception):
    """ Dumbarb needs to exit (e.g. our engines misbehave but we can't kill) """
    pass

################################### classes ####################################

class SgfWriter:
    """ Collects game data and writes it to an SGF file. """
    def __init__(self, gameSettings, whiteName, blackName, gameName, eventName):
        """ Construct an SgfWriter object.

        Arguments:
        gameSettings -- a GameSettings object
        whiteName -- name of the white player
        blackName -- name of the black player
        gameName -- name of the game
        eventName -- name of the event
        """
        self.datesIso = datetime.datetime.now().date().isoformat()
        self.result = None
        self.blacksTurn = True
        self.movesString = ''
        self.gameSettings = gameSettings
        self.whiteName = whiteName
        self.blackName = blackName
        self.gameName = gameName
        self.eventName = eventName
        self.errorEncountered = False

    def writeToFile(self, filename, directory=None):
        """ Save a finished game as an SGF file.

        Arguments:
        filename -- output file with or without path
        directory -- directory for file (default: current working dir)
        """
        assert self.result, 'Attempt to write SGF with no result set'

        if directory:
                filename = os.path.join(directory, filename)

        if (self.errorEncountered):
            printErr('\nSkipped SGF file due to errors: {0}'.format(filename))
            return False

        try:
            with open(filename, 'w', encoding='utf-8') as file:
                begin = SGF_BEGIN.format(SGF_AP_VER, # 0 AP
                                'Chinese', # 1 RU
                                self.gameSettings.boardSize, # 2 SZ
                                self.gameSettings.komi, # 3 KM
                                self.gameName, # 4 GN
                                self.whiteName, # 5 PW
                                self.blackName, # 6 PB
                                self.datesIso, # 7 DT
                                self.eventName, # 8 EV
                                self.result) # 9 RE
                file.write(begin)
                file.write(self.movesString)
                file.write(SGF_END)
        except OSError as e:
            msg = 'nError writing SGF file "{0}":'
            printErr(msg.format(filename), sub=e)
            return False

        return True

    def addMove(self, coord):
        """ Add a move and add today's date to SGF game dates if necessary.

        Arguments:
        coord -- the board coordinates in GTP notation
        """
        if self.errorEncountered:
            return False

        todayIso = datetime.datetime.now().date().isoformat()
        if todayIso not in self.datesIso: self.datesIso += ',' + todayIso
        color = BLACK if self.blacksTurn else WHITE

        if coord.lower() == 'pass':
            letterLtoR = ''
            letterTtoB = ''
        else:
            try:
                gtpLetters = string.ascii_lowercase.replace('i','')
                idxLtoR = gtpLetters.index(coord[0].lower())
                if idxLtoR > self.gameSettings.boardSize:
                    raise ValueError('move outside the board')
                idxTtoB = abs(int(coord[1:])-self.gameSettings.boardSize)
                if idxTtoB > self.gameSettings.boardSize:
                    raise ValueError('move outside boart board')
                letterLtoR = string.ascii_lowercase[idxLtoR]
                letterTtoB = string.ascii_lowercase[idxTtoB]
            except ValueError as e:
                msg = 'SGF: Bad move format: "{0}". Ignoring subsequent moves.'
                printErr(msg.format(coord), sub=e)
                self.errorEncountered = True
                return False
        mvString = SGF_MOVE.format(color, letterLtoR, letterTtoB)
        self.movesString += mvString
        self.blacksTurn = not self.blacksTurn
        return True

    def addMoveList(self, moveList):
        """ Add a list moves using self.addMove.

        Argumetns:
        moveList -- a list of move coordinate strings (GTP notation)

        """
        for move in moveList:
            self.addMove(move)

    def setResult(self, winner, plusText=None):
        """ Add the game result to the SGF data.

        Arguments:
        winner -- one of WHITE, BLACK, RESULT_JIGO, RESULT_NONE, RESULT_ERR
        plusText -- text after + if W or B won: Time, Resign, or a number
                    indicating score difference (default None)
        """
        if winner == WHITE:
            self.result = 'W+' + plusText
        elif winner == BLACK:
            self.result = 'B+' + plusText
        elif winner == RESULT_JIGO:
            self.result = '0' #SGF for jigo
        else:
            self.result = '?' #SGF for 'unknown result'

class GameSettings:
    """ Holds go game settings (board size, komi, time settings). """
    def __init__(self, boardSize=19, komi=7.5, mainTime=0, periodTime=5,
                 periodCount=1, timeSys=2):
        """ Construct a GameSettings object.

        Arguments:
        boardSize = size of the board (default 19)
        komi = komi (default 7.5)
        mainTime = main time in seconds (default 0)
        periodTime = period time in seconds (default 5)
        periodCount = periods/stones for Japanese/Canadian byo yomi (default 1)
        timeSys = time system: 0=none, 1=absolute, 2=Canadian, 3=Japanese byo
                  yomi (default 2)
        """
        self.boardSize = boardSize
        self.komi = komi
        self.mainTime = mainTime
        self.periodTime = periodTime
        self.periodCount = periodCount
        self.timeSys = timeSys

    def isNoTime(self):  return self.timeSys == 0
    def isAbsTime(self): return self.timeSys == 1
    def isCndByo(self):  return self.timeSys == 2
    def isJpnByo(self):  return self.timeSys == 3

class GtpEngine:
    """Talks with a GTP engine via pipes, multi-threaded."""

    def __init__(self, name=None, ein=None, eout=None, eerr=None):
        """ Construct a GtpEngine object from EITHER two streams (ein and eout)
        OR a Popen object.

        Arguments:
        ein -- engine input stream (default None)
        eout -- engine output stream (default None)
        process -- a subprocess.Popen object (running child process)
                (default None)
        name -- the engine name for logging/display purposes (default None)
        """
        self.name = name
        self.ein = ein
        self.eout = eout
        self.eerr = eerr

        self.gtpDebug = False
        self.showDebug = False
        self.color = None

        self.quitSent = False
        self.threadEout = None
        self.threadEerr = None
        self.responseQ = None
        self.errFile = None
        self.errLock = threading.Lock()
        self.gtpDown = threading.Event()

    def _threadsInit(self):
        """ Initialize and run reader threads, response queue

        <Private use>
        """
        self.gtpDown.clear()

        if self.eout:
            self.responseQ = queue.Queue()
            self.threadEout = threading.Thread(name='GTP-rdr',
                        target=self._rGtpLoop, daemon=True)
            self.threadEout.start()
        if self.eerr:
            self.threadEerr = threading.Thread(name='err-rdr',
                        target=self._rErrLoop, daemon=True)
            self.threadEerr.start()

    def _threadsJoin(self):
        """ Join the threads for shutdown

        <Private use>
        """
        if self.showDebug:
            self._engErr('Joining read threads...')
        if self.threadEout:
            self.threadEout.join()
        if self.threadEerr:
            self.threadEerr.join()

    def _rGtpLoop(self):
        """ Read GTP and put into queue, signal when stream down

        <Private use>

        Removes CRs per GTP2, waits for termination with two newlines then
        decodes into a right-stripped string. Sets self.gtpDown when it can no
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
                if self.gtpDebug:
                    self._engErr('Received: {0}'.format(response))
                self.responseQ.put(response)
                bar = bytearray()
            # EOF
            if self.showDebug:
                self._engErr('GTP -EOF-')
            self.gtpDown.set()
        except OSError as e:
            self._engErr('GTP read error: {1}'.format(e))
            self.gtpDown.set()

    def _rErrLoop(self):
        """ Read engine's stderr, either display it, log to file, both (or none)

        <Private use>

        Writing/changing the self.errFile is sync'd with a lock.
        """
        try:
            for byteline in self.eerr:
                if not self.suppressErr:
                    self._engErr(byteline.decode().rstrip(), prefix='')
                if self.errFile:
                    with self.errLock:
                        self.errFile.write(byteline)
            # EOF
            if self.showDebug:
                self._engErr('stderr -EOF-')
        except OSError as e:
            self._engErr('stderr read error: {1}'.format(e))

    def _rawRecvResponse(self, timeout):
        """ Dequeue a response within timeout, also checking for gtpDown event

        <Private use>
        """
        begin = datetime.datetime.utcnow()
        retries = 3
        while (datetime.datetime.utcnow() - begin).total_seconds() < timeout:
            try:
                return self.responseQ.get(block=True, timeout=Q_TIMEOUT)
            except queue.Empty:
                if self.gtpDown.is_set():
                    retries -= 1
                if retries <= 0:
                    raise GtpShutdown
        raise GtpTimeout('Timeout exceeded ({0})'.format(timeout))

    def _rawSendCommand(self, command, raiseExceptions=True):
        """ Send a GTP command and return True; encode and ensure proper newline
        termination.

        <Private use>

        Can return False if there was an error and it was called with
        raiseExceptions=False.

        Arguments:
        command -- a string containing the GTP command and any arguments
        raiseExceptions -- whether to raise GtpProcessError or return False
                           on OS errors (default True)
        """
        if self.gtpDebug:
            self._engErr(' Sending: {0}'.format(command))
        try:
            self.ein.write(command.rstrip().encode() + b'\n')
        except OSError as e:
            if self.showDebug:
                self._engErr('Cannot send command to engine')
            if raiseExceptions:
                msg = 'Cannot send command to engine: {0}'
                raise GtpProcessError(msg.format(e)) from None
            else:
                return False
        if command.lower().strip() == 'quit':
            self.quitSent = True
        return True

    def _engErr(self, message, **kwargs):
        """ Write an error message, prefixed with the engine's name

        <Private use>

        Arguments:
        message -- the message

        Keyword arguments are passed on to printErr.
        """
        name = self.name if hasattr(self, 'name') else '<undef>'
        outmsg = '[{0}] {1}'.format(name, str(message))
        printErr(outmsg, **kwargs)

    def setErrFile(self, filename=None):
        """ Set self.errFile to a new file in a thread-safe manner

        This method acquires a lock, closes any previously opened errFile,
        opens the new one (for binary writing) and sets it be the new errFile
        before releasing the lock. To close the open errLock, call with no args.

        Arguments:

        filename -- file to open (Default None, which just closes any open file)
        """
        if self.errLock.acquire(blocking=True, timeout=1.5):
            if self.errFile:
                self.errFile.close()
            if filename:
                self.errFile = open(filename, 'wb')
            self.errLock.release()
        else:
            msg = '[{0}] Could not acquire errLock! Something is very wrong!'
            raise AllAbort(msg.format(self.name))

    def quit(self, timeout):
        """ Send the quit command to the engine (no output)

        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        """
        if not self.quitSent:
            self.sendCommand('quit', timeout=timeout)

    def setColor(self, color):
        """ Set the color for the engine (internal; produces no GTP)

        Argumetns:

        color -- WHITE or BLACK
        """
        assert color in [BLACK, WHITE], 'Invalid color: {0}'.format(color)
        self.color = color
        if self.gtpDebug:
            self._engErr('* now playing as {0}'.format(color))

    def sendCommand(self, command, timeout=GTP_TIMEOUT):
        """ Send a GTP command that produces no output.

        Arguments:
        commmand -- GTP command and its arguments, if any
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)

        Exceptions: GtpTimeout, GtpIllegalMove, GtpResponseError
        """
        self._rawSendCommand(command)
        try:
            response = self._rawRecvResponse(timeout=timeout)
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

    def getResponseFor(self, command, timeout=GTP_TIMEOUT):
        """ Send a GTP command and return its output

        Arguments:
        commmand -- GTP command and its arguments, if any
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)

        Exceptions: GtpTimeout, GtpCannotScore, GtpResponseError

        """
        self._rawSendCommand(command)
        try:
            response = self._rawRecvResponse(timeout=timeout)
        except GtpTimeout:
            msg = '[{0}] GTP timeout({1}), command: {2}'
            raise GtpTimeout(msg.format(self.name, timeout, command)) from None

        if response.lower() == '? cannot score':
            msg = '[{0}] GTP scorer problem: "{1}" (cmd: "{2}")'
            raise GtpCannotScore(msg.format(self.name, response, command))

        if response [:2] != '= ':
            msg = '[{0}] GTP response error: "{1}" (cmd: "{2}")'
            raise GtpResponseError(msg.format(self.name, response, command))
        return response[2:]

    def clearBoard(self, timeout=GTP_TIMEOUT):
        """ Clear the engine's board in preparation for a new game

        Arguments:
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        """
        self.sendCommand('clear_board', timeout=timeout)

    def timeLeft(self, args, timeout=GTP_TIMEOUT):
        """ Send the GTP time_left command with the supplied arguments.

        Arguments:
        args -- tuple/iter with two arguments to GTP time_left
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        """
        assert self.color in [BLACK, WHITE], \
                    'Invalid color: {0}'.format(self.color)
        cmd = 'time_left {0} {1} {2}'
        self.sendCommand(cmd.format(self.color, args[0], args[1]),
                    timeout=timeout)

    def placeOpponentStone(self, coord, timeout=GTP_TIMEOUT):
        """ Place a stone of the opponent's color on the engine's board.

        Arguments:
        coord -- the board coordinates in GTP notation
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)

        Special exception: GtpIllegalMove
        """
        assert self.color in [BLACK, WHITE], \
                    'Invalid color: {0}'.format(self.color)
        if self.color == BLACK:
            oppColor = WHITE
        else:
            oppColor = BLACK
        return self.sendCommand('play {0} {1}'.format(oppColor, coord),
                    timeout=timeout)

    def finalScore(self, timeout=GTP_SCO_TIM):
        """ Return the final score as assessed by the engine

        Arguments:
        timeout -- seconds to wait before raising GtpTimeout (def GTP_SCO_TIM)

        Special exception: GtpCannotScore
        """
        return self.getResponseFor('final_score', timeout=timeout)

    def move(self, timeout):
        """ Return a generated move from the engine (in GTP notation)

        Arguments:
        timeout -- max timeout before raising GtpTimeout (should be higher than
        time controls)
        """
        assert self.color in [BLACK, WHITE], \
                    'Invalid color: {0}'.format(self.color)
        return self.getResponseFor('genmove ' + self.color, timeout=timeout)

    def playMoveList(self, moveList, firstColor=BLACK, timeout=GTP_TIMEOUT):
        """ Place stones of alternating colors on the coordinates given in
        moveList

        Arguments:
        moveList -- list of strings containing board coordinates in GTP notation
        firstColor -- one of BLACK or WHITE: start w/this color  (default BLACK)
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
                   valid separately for each 'play' (one stone) command

        """
        color = firstColor
        for move in moveList:
            self.sendCommand('play {0} {1}'.format(color, move), timeout)
            color = WHITE if color == BLACK else BLACK

    def scoreFromMoveList(self, moveList, timeout=GTP_TIMEOUT):
        """ Returns engine's score for a game by placing all the stones first

        This just calls the methods clearBoard(), playMoveList(moveList) and
        returns         finalScore().

        Arguments:
        moveList -- list of strings containing board coordinates in GTP notation
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        """
        self.clearBoard()
        self.playMoveList(moveList)
        return self.finalScore()

    def gameSetup(self, settings, timeout=GTP_TIMEOUT):
        """ Send a number of GTP commands setting up game parameters

        Sets up board size, komi, time system and time settings. The Japanese
        byo yomi time system requires engine support of the GTP extension
        command kgs-time_settings

        Arguments:
        settings -- a GameSettings object containing the game settings
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        """
        m = settings.mainTime
        p = settings.periodTime
        c = settings.periodCount
        self.sendCommand('boardsize ' + str(settings.boardSize))
        self.sendCommand('komi ' + str(settings.komi))
        if settings.isJpnByo():
            cmd = 'kgs-time_settings byoyomi {0} {1} {2}'
            self.sendCommand(cmd.format(m, p, c))
        else:
            if settings.isAbsTime():
                p = 0 # GTP convention for abs time (=0)
            elif settings.isNoTime():
                p = 1 # GTP convention for no time sys (>0)
                c = 0 # GTP convention for no time sys (=0)
            self.sendCommand('time_settings {0} {1} {2}'.format(m, p, c))

    def verifyCommands(self, commandSet, showDiagnostics=False,
                    timeout=GTP_TIMEOUT):
        # TODO return list of missing commands, let caller print diag
        """ Verify engine supports commands, optionally print diagnostics

        An GtpMissingCommands exception is raised, if the engine does not pass

        Arguments:
        commandSet -- a set of strings, the commands for which to check
        showDiagnostics -- print a diagnostic messages
        timeout -- seconds to wait before raising GtpTimeout (def GTP_TIMEOUT)
        time
        """
        knownCmds = set(self.getResponseFor('list_commands').split())
        passed = True if knownCmds >= commandSet else False

        if not passed or showDiagnostics:
            fmtArgs = {}
            for cmd in ['name', 'version', 'protocol_version']:
                resp = self.getResponseFor(cmd, timeout=timeout) if cmd in knownCmds else '<?>'
                fmtArgs[cmd] = resp
            self._engErr(ENGINE_DIAG.format(**fmtArgs) + \
                            (ENGINE_OK if passed else ENGINE_FAIL))
        if not passed:
            missingCmds = str(commandSet - knownCmds)
            msg = '[{0}] missing required GTP commands: {1}'
            raise GtpMissingCommands(msg.format(self.name, missingCmds))

class TimedEngine(GtpEngine):
    """ Add timekeeping and additional stats to GtpEngine
    """
    def __init__(self, name, settings=None, timeTolerance=0, moveWait=0,
                **kwargs):
        """ Init a TimedEngine

        Arguments:
        settings -- a GameSettings object containing the game settings (a new
                    one will be created, if it is not supplied)
        timeTolerance -- time tolerance in seconds (microsecond precision)
        moveWait -- time to wait between moves (seconds)
        **kwargs -- arguments to pass to GtpEngine __init__
        """
        super().__init__(name, **kwargs)
        self.settings = settings if settings else GameSettings()
        self.timeTolerance = timeTolerance
        self.moveWait = moveWait

    def _checkinDelta(self, delta):
        """ Check in a new move, update engine timers, return whether time
         controls violated.

         <Private use>

        Arguments:
        delta -- a timedate.delta object containing the move delta (the time
                 spent on the move)
        """
        stg = self.settings

        self.totalTimeTaken += delta
        if delta > self.maxTimeTaken: self.maxTimeTaken = delta

        # No time controls -- always return False (no violation)
        if stg.isNoTime() or self.timeTolerance < 0:
            return False

        # Absolute
        if stg.isAbsTime():
            timeLeft = self.mainTime - self.totalTimeTaken.total_seconds()
            self.gtpTimeLeft = ((int(timeLeft) if timeLeft > 0 else 0), 0)
            nextMoveTimeout = timeLeft + self.timeTolerance
            self.moveTimeout = nextMoveTimeout
            return nextMoveTimeout > 0

        # Not yet in byo yomi (but might fall through to byo yomi)
        if not self.inByoyomi:
            mainLeft = stg.mainTime - self.totalTimeTaken.total_seconds()
            if mainLeft > 0:
                self.gtpTimeLeft = (int(mainLeft), 0)
                if stg.isJpnByo():
                    additional = stg.periodTime * stg.periodCount
                else:
                    additional = stg.periodTime
                self.moveTimeout = mainLeft + additional + self.timeTolerance
                return False # still in main time
            # starting byo yomi
            self.inByoyomi = True
            delta = datetime.timedelta(seconds=(-mainLeft))

        # Japanese byo yomi
        if stg.isJpnByo():
            exhaustedPeriods = int(delta.total_seconds() / stg.periodTime)
            if exhaustedPeriods >= self.periodsLeft:
                deltaWithTolerance = max(0,
                            delta.total_seconds() - self.timeTolerance)
                exhaustedPeriods = int(deltaWithTolerance / stg.periodTime)
            self.periodsLeft -= exhaustedPeriods

            self.gtpTimeLeft = (stg.periodTime, max(self.periodsLeft, 1))
            self.moveTimeout = max(self.periodsLeft, 1) * stg.periodTime \
                                 + self.timeTolerance
            return self.periodsLeft <= 0

        # Canadian byo yomi
        if stg.isCndByo():
            self.periodTimeLeft-=delta.total_seconds()
            if self.periodTimeLeft + self.timeTolerance < 0:
                violation=True
            else:
                violation=False
            self.stonesLeft -= 1
            if self.stonesLeft == 0:
                self.stonesLeft = stg.periodCount
                self.periodTimeLeft = stg.periodTime
                self.gtpTimeLeft = (self.periodTimeLeft, self.stonesLeft)
            else:
                self.gtpTimeLeft = (max(int(self.periodTimeLeft), 0),
                            self.stonesLeft)
            self.moveTimeout = max(self.periodTimeLeft, 0) + self.timeTolerance
            return violation

        return True #don't know this timeSys; fail

    def _resetGameTimekeeping(self):
        """ Reset timekeeping in preparation for a new game

        <Private use>
        """
        s = self.settings

        # init various
        self.maxTimeTaken = datetime.timedelta()
        self.totalTimeTaken = datetime.timedelta()
        self.periodsLeft = s.periodCount if s.isJpnByo() else None
        self.stonesLeft  = s.periodCount if s.isCndByo() else None
        self.periodTimeLeft = s.periodTime if s.isCndByo() else None
        self.inByoyomi = False

        # set initial GTP time left
        if not s.isNoTime():
            if s.mainTime > 0:
                self.gtpTimeLeft = (s.mainTime, 0)
            else:
                self.gtpTimeLeft = (s.periodTime, s.periodCount)
        else:
            self.gtpTimeLeft = None

        # set initial exact move timeout
        if not s.isNoTime():
            if s.isCndByo():
                additional = s.periodTime
            elif s.isJpnByo:
                additional = s.periodTime * s.periodCount
            else:
                additional = 0
            self.moveTimeout = s.mainTime + additional
        else:
            self.moveTimeout = None

    def newGame(self, color):
        """ Prepare for a new game: reset timekeeping, clear board, set color

        Argumetns:
        color -- WHITE or BLACK
        """
        self.clearBoard()
        self._resetGameTimekeeping()
        self.setColor(color)
        self.movesMade = 0

    def timedMove(self):
        """ Play a move and return a (coords, violation, delta) tuple

        The returned tuple contains move coordinates (GTP notation), whether
        the time controls (with tolerance) were violated (Booelan) and the
        move delta (time the engine used to think).
        """
        if self.timeTolerance >= 0 and not self.settings.isNoTime():
            self.timeLeft(self.gtpTimeLeft)
            tmout = self.moveTimeout + GTP_GMT_EXT
        else:
            tmout = GTP_GMT_NON

        beforeMove = datetime.datetime.utcnow()
        move = self.move(tmout)
        delta = datetime.datetime.utcnow() - beforeMove
        self.movesMade += 1 # increments on resign & timeout, unlike numMoves

        return(move, self._checkinDelta(delta), delta)

class ManagedEngine(TimedEngine):
    """ Adds a context/resource manager to TimedEngine, builds from config.

    Main focus is on properly shutting down, killing sub-processes, closing fds.
     """
    def __init__(self, name, match):
        """ Inits a Managed Engine

        Arguments
        name -- name of the engine
        match -- the match where the engine will play
        """
        super().__init__(name, settings=match.gameSettings,
                               timeTolerance=match.timeTolerance,
                               moveWait=match.moveWait)
        self.popen = None
        self.restarts = 0
        self.cmdLine = match.cnf[name]['cmd']
        self.wkDir = match.cnf[name].get('wkDir', fallback=None)
        self.reqCmds = set()
        if self.name in match.engineNames:
            self.reqCmds |= match.reqCommands
        if self.name == match.scorerName:
            self.reqCmds |= match.reqCmdScorer

        self.showDiagnostics = match.showDiagnostics
        self.showDebug = match.showDebug
        self.gtpDebug = match.gtpDebug
        self.suppressErr = match.cnf[name].getboolean('quiet',
                    fallback=match.suppressErr)
        self.logStdErr = match.cnf[name].getboolean('logStdErr',
                    fallback=match.logStdErr)

    def __enter__(self):
        """ Enters ManagedEngine context

        <Private use>
        """
        if self.showDebug:
            self._engErr('Entering context.')
        while True:
            try:
                self._invoke()
                break
            except GtpException:
                printErr('E')
                self.restart()
        return self

    def __exit__(self, et, ev, trace):
        """ Exits ManagedEngine context, calls shutdown() and closes stderr log

        <Private use>
        """
        if self.showDebug:
            self._engErr('Exiting context (Err: {0}, {1}).'.format(et, ev))
        self.shutdown()
        self.setErrFile()

    def _invoke(self, isRestart=False):
        """ Invokes the subproccess and starts reader threads

        Arguments:
        isRestart -- skip some diagnostic messages (default False)

        <Private use>
        """
        if self.popen:
            return

        if self.showDiagnostics and not isRestart:
            self._engErr(ENGINE_DIR.format(dir=self.wkDir))
            self._engErr(ENGINE_CMD.format(cmd=self.cmdLine))

        # change to wkDir, if supplied
        # (do not use popen's cwd, as behaviour platform-dependant)
        if self.wkDir:
            startingWkDir = os.getcwd()
            os.chdir(self.wkDir)

        # set up a platform-appropriate cmdLine for Popen, start the subprocess
        windows = sys.platform.startswith('win')
        if (windows):
            platformCmd = self.cmdLine
        else:
            platformCmd = shlex.split(self.cmdLine)
        try:
            self.popen = subprocess.Popen(platformCmd, bufsize=0,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        except OSError as e:
            msg = '[{0}] Could not run command:\n{1}\ncmd: {2}\ndir: {3}'
            raise GtpProcessError(msg.format(self.name, e,
                        platformCmd, os.getcwd())) from None

        # change back to starting working dir
        if self.wkDir:
            os.chdir(startingWkDir)

        # engine's in/out/err
        self.eout = self.popen.stdout
        self.ein = self.popen.stdin
        self.eerr = self.popen.stderr

        # start threads
        self._threadsInit()

        # verify commands supported
        self.verifyCommands(self.reqCmds, self.showDiagnostics)

    def shutdown(self):
        """ Shutdown engine, take care of subprocess, threads, fds.
        """
        if not self.popen:
            self._engErr('Shutdown: nothing to shut down.')
            return

        if self.showDebug:
            self._engErr('Shutting down.')

        if not self.quitSent:
            if self.showDebug:
                self._engErr('Engine was not quit, sending "quit"')
            sent = self._rawSendCommand('quit', raiseExceptions=False)
            if not sent:
                self._engErr('Sending "quit" failed')

        if self.showDebug:
            self._engErr('Waiting for process (max {0}s)'.format(WAIT_QUIT))
        try:
            self.popen.wait(WAIT_QUIT)
        except subprocess.TimeoutExpired as e:
            self._engErr('Killing process: ({0})'.format(e))
            self.popen.kill()

        self._threadsJoin()
        self.popen.stdout.close()
        self.popen.stderr.close()
        self.popen.stdin.close()
        self.popen.wait()

        poll = self.popen.poll()
        if poll == None:
            msg = '[{0}] Somehow, shutdown seems to have failed.'
            raise AllAbort(msg.format(self.name))
        self.popen = None
        msg = 'Shutdown successful (exit code = {0}).'
        self._engErr(msg.format(poll))

    def restart(self):
        """ Restart the engine
        """
        self.restarts += 1
        if self.restarts > 20:
            msg = 'Engine {0} restarted more than 20 times.'
            raise MatchAbort(msg.format(self.name))
        self._engErr('Restarting...')
        self.shutdown()
        try:
            self._invoke(isRestart=True)
        except GtpException:
            self.restart()

    def addGameResultToStats(self, game):
        """ Update engine stats with the game result supplied in game

        Arguments:
        game -- a Game object containing the game result
        """
        assert self.color in [BLACK, WHITE], \
                    'Invalid color: {0}'.format(self.color)

        # create stats array, if it doesn't exist
        if not hasattr(self, 'stats'):
            self.stats = [0 for x in range(8)]

        # update games won/totals:
        self.stats[1] += 1 # total games
        if self.color == WHITE:
            self.stats[3] += 1 # total as W
            if game.winner == WHITE:
                self.stats[0] += 1 # total wins
                self.stats[2] += 1 # wins as W
        else: # self is BLACK
            self.stats[5] += 1 # total as B
            if game.winner == BLACK:
                self.stats[0] += 1 # total wins
                self.stats[4] += 1 # wins as B

        # update max time/move overall
        maxtt = self.maxTimeTaken.total_seconds()
        if maxtt > self.stats[6]: self.stats[6] = maxtt # max t/move for match

        #total time
        self.stats[7] += self.totalTimeTaken.total_seconds()

    def printMatchStats(self):
        """ Prints some match stats to stderr
        """
        self._engErr(ENGINE_MSTA.format(stats=self.stats))

class Match:
    """ Plays whole matches, stores settings, manages context

    Context manager managing ManagedEngine instances, the match logfile, and
    the directories needed (match dir, stderr, SGFs). GTP engines are not
    created/invoked before the context of a Match is entered. This class ensures
    (together with ManagedEngine) that all engines are terminated normally or,
    failing that, killed off before starting another match. If this somehow
    fails, AllAbort is called, cancelling all further Matches, since a system
    with processes running wild is likely to prouce skewed match results.
    """
    def __init__(self, sectionName, cnf):
        """ Initializes a Match from DumbarbConfig and a match section name

        Arguments:
        sectionName -- the match name, a name of a section in the config file(s)
        cnf -- DumbarbConfig instance containing the configuration
        """
        # set when entering context
        self.estack = None
        self.engines = None
        self.scorer = None
        self.outStream = None
        self.createdMatchDir = None

        # config
        self.cnf = cnf
        section = cnf[sectionName]
        snameElems = sectionName.split()
        for elm in snameElems:
            if not self._nameOK(elm):
                raise ConfigError(ENGINE_BNAM.format(badname=elm))
        try:
            # GameSettings object
            self.gameSettings = GameSettings(
                        boardSize=int(section.get('boardSize', 19)),
                        komi=float(section.get('komi', 7.5)),
                        mainTime=int(section.get('mainTime', 0)),
                        periodTime=int(section.get('periodTime', 2)),
                        periodCount=int(section.get('periodCount', 0)),
                        timeSys=int(section.get('timeSys', 2)))

            # other config values
            self.name = ' '.join(snameElems)
            uscName = '_'.join(snameElems)
            self.logBasename = uscName + '.log'
            self.uncheckedMatchDir = uscName
            self.engineNames = snameElems[:2]
            self.numGames = int(section.get('numGames', 100))
            self.consecPassesToEnd = int(section.get('consecutivePasses', 2))
            self.matchWait = float(section.get('matchWait', 1))
            self.gameWait = float(section.get('gameWait', 0.5))
            self.moveWait = float(section.get('moveWait', 0))
            self.timeTolerance = float(section.get('timeTolerance', 0))
            self.scorerName = section.get('scorer', None)
            self.disableSgf = section.getboolean('disableSgf', False)
            self.enforceTime = section.getboolean('enforceTime', False)
            self.suppressErr = section.getboolean('quiet', False)
            self.logStdErr = section.getboolean('logStdErr', True)
        except ValueError as e:
            msg = 'Config value error for match [{0}]: {1}'
            raise ConfigError(msg.format(section.name, e))

        # set of GTP commands engines are required to support
        self.reqCommands = {'boardsize', 'komi', 'genmove', 'play',
                    'clear_board', 'quit'}
        if self.gameSettings.timeSys > 0:
            self.reqCommands.add('time_left')
        if self.gameSettings.timeSys == 3:
            self.reqCommands.add('kgs-time_settings')
        else:
            self.reqCommands.add('time_settings')

        # set of GTP commands a scorer engine would be required to support
        self.reqCmdScorer = (self.reqCommands | {'final_score'}) \
                            - {'genmove', 'time_left'}

        # from args
        self.startWith = cnf.startWith
        self.showDiagnostics = cnf.showDiagnostics
        self.showDebug = cnf.showDebug
        self.showProgress = cnf.showProgress
        self.gtpDebug = cnf.gtpDebug

        # field widths for formatting output
        self.maxDgts = len(str(self.numGames))
        self.nWidth =  max(len(self.engineNames[0]), len(self.engineNames[1]),
                len(RESULT_JIGO), len(RESULT_NONE), len(RESULT_ERR))

    def __enter__(self):
        """ Create and put engines and an opened logfile on an ExitStack, mkdirs

        <Private use>
        """
        self.estack = contextlib.ExitStack()

        # start engines
        self.engines = [self.estack.enter_context(ManagedEngine(name, self))
                            for name in self.engineNames]

        # create scorer as separate ManagedEngine, if necessary
        if self.scorerName:
            try:
                i = self.engineNames.index(self.scorerName)
                self.scorer = self.engines[i]
            except ValueError:
                self.scorer = self.estack.enter_context(
                            ManagedEngine(self.scorerName, self))

        # match dir
        self.createdMatchDir = self._mkMatchDir()

        # SGF subdir
        if not self.disableSgf:
            self.createdSgfDir = self._mkSub(SGF_SUBDIR)

        # err subdir
        createErrDir = False
        for engine in self.engines:
            if engine.logStdErr:
                createErrDir = True
                break
        if createErrDir:
            self.createdErrDir = self._mkSub(ERR_SUBDIR)

        # results file
        logFile = os.path.join(self.createdMatchDir, self.logBasename)
        self.outStream = self.estack.enter_context(open(logFile, 'w'))

        return self

    def __exit__(self, et, ev, trace):
        """ Close the ExitStack (ManagedEngines, open logfile)

        <Private use>
        """
        if self.showDebug:
            msg = 'Closing exit stack: {0} (Err: {1}: {2})'
            etname = et.__name__ if et else None
            printErr(msg.format(self.name, etname, ev))
        self.estack.close()
        return False

    def _mkMatchDir(self):
        """ Make & return match dir, append -001, -002, etc. if it exists

        <Private use>
        """
        tryDir = self.uncheckedMatchDir
        if os.path.exists(tryDir):
            for i in range(1, 999):
                tryDir = self.uncheckedMatchDir + '-{0:03}'.format(i)
                if not os.path.exists(tryDir):
                    msg = '"{0}" already exists; storing log/SGFs in "{1}"'
                    printErr(msg.format(self.uncheckedMatchDir, tryDir))
                    break
        try:
            os.mkdir(tryDir)
        except OSError as e:
            msg = 'Could not create results directory "{0}":\n    {1}'
            raise MatchAbort (msg.format(tryDir, e)) from None
        return tryDir

    def _mkSub(self, subdir):
        """ Make a subdir in the match dir, return its name

        <Private use>
        Arguments:
        subdir -- the directory to create and return
        """
        dirName = os.path.join(self.createdMatchDir, subdir)
        os.mkdir(dirName)
        return dirName

    def _printIndicator(self, gameNum):
        """ Print a character indicating a game has been finished

        <Private use>

        A dot is printed by default, the tens digit of gameNum every ten games,
        and a newline every 100.

        Arguments:
        gameNum -- the game number for which to print an indicator
        """
        char = str(gameNum)[-2:-1] if gameNum % 10 == 0 else '.'
        end = '\n' if gameNum %100 == 0 else ''
        printErr(char + end, skipformat=True)

    def _output(self, string, flush=False):
        """ Write to the output stream, optionally flush

        <Private use>

        Arguments:
        string -- string to write
        flush -- whether to flush (default False)

        """
        self.outStream.write(string)
        if flush: self.outStream.flush()

    def _outputResult(self, gameNum, game):
        """ Write a result line to the output stream

        <Private use>

        Arguments:
        gameNum -- game number
        game -- Game object of a finished game

        """
        # print pre-result string
        isoDate=datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
        self._output(FMT_PRE_RES.format(stamp =isoDate, seqno = gameNum,
                    swidth = self.maxDgts, nwidth = self.nWidth,
                    name1 = self.engines[0].name, col1 = self.engines[0].color,
                    name2 = self.engines[1].name, col2 = self.engines[1].color))

        # get/caluclate engine time stats
        engStats = []
        for engine in self.engines:
            if engine.movesMade > 0:
                avgtt = engine.totalTimeTaken.total_seconds() / engine.movesMade
            else:
                avgtt = 0
            engStats.append({'name': engine.name,
                            'maxtt': engine.maxTimeTaken.total_seconds(),
                            'tottt': engine.totalTimeTaken.total_seconds(),
                            'avgtt': avgtt,
                            'moves': engine.movesMade})

        # print result, time stats, move count, time violators string
        if game.winner == WHITE:
            self._output(FMT_WIN_W.format(
                        name=game.whiteEngine.name, nwidth=self.nWidth))
        elif game.winner == BLACK:
            self._output(FMT_WIN_B.format(
                        name=game.blackEngine.name, nwidth=self.nWidth))
        else:
            self._output(FMT_ALT_RES.format(
                        result=game.winner, nwidth=self.nWidth))
        self._output(FMT_REST.format(
                        name1 = engStats[0]['name'],
                        maxtt1 = engStats[0]['maxtt'],
                        tottt1 = engStats[0]['tottt'],
                        avgtt1 = engStats[0]['avgtt'],
                        name2 = engStats[1]['name'],
                        maxtt2 = engStats[1]['maxtt'],
                        tottt2 = engStats[1]['tottt'],
                        avgtt2 = engStats[1]['avgtt'],
                        mv1 = engStats[0]['moves'],
                        mv2 = engStats[1]['moves'],
                        moves = game.numMoves,
                        reason = game.winReason,
                        vio = game.timeVioStr if game.timeVioStr else VIO_NONE,
                        nwidth = self.nWidth),
                    flush = True)

    @staticmethod
    def _nameOK(name):
        """ Check if name follows the rules

        <Private use>
        """
        try:
            nameOK = name[0] in ENGALW_FRST and len(name) <= ENGALW_MAXC \
                        and set(name) <= set(ENGALW_CHAR) and name[-1:] != '.'
        except ValueError:
            return False
        return nameOK

    def _printMatchStats(self):
        """ Print overall match stats, calling both engines' printMatchStats()

        <Private use>
        """
        if self.showProgress and not self.numGames % 100 == 0:
            printErr(prefix='')
        printErr('Match ended. Overall stats:')
        for engine in self.engines:
            engine.printMatchStats()

    def play(self):
        """ Play the match, handle result & stderr logging, SGF
        """
        if self.showDiagnostics:
            printErr('============ match {0} ============'.format(self.name))

        # check startWith is valid
        if self.startWith > self.numGames:
            msg = 'Cannot start with game {0} when the whole match is {1} games'
            raise MatchAbort(msg.format(self.startWith, self.numGames))

        # set of all engines running for this game
        allEngines = set(self.engines)
        if self.scorer:
            allEngines.add(self.scorer)

        # board settings
        for engine in allEngines:
            while True:
                try:
                    engine.gameSetup(self.gameSettings)
                    break
                except GtpException:
                    engine.restart() # will raise MatchAbort after several

        # match wait
        if self.matchWait:
            time.sleep(self.matchWait)

        # match loop
        white, black = self.engines;
        for gameNum in range(self.startWith, self.numGames + 1):
            # SGF prepare
            sgfFile = FN_FORMAT.format(num=gameNum, ext='sgf')
            if not self.disableSgf:
                sgfWr = SgfWriter(self.gameSettings, white.name, black.name,
                            'game {0}'.format(gameNum),
                            'dumbarb {0}-game match'.format(self.numGames))

            # play the game, write result line, set errfile
            if self.gameWait: time.sleep(self.gameWait)
            for engine in allEngines:
                if engine.logStdErr:
                    fname = FN_FORMAT.format(
                                num=gameNum, ext=engine.name + '.log')
                    engine.setErrFile(os.path.join(self.createdErrDir, fname))
            game = Game(white, black, self)
            game.play()


            self._outputResult(gameNum, game)

            # print dot
            if self.showProgress:
                self._printIndicator(gameNum)

            # SGF write to file
            if not self.disableSgf:
                sgfWr.addMoveList(game.moveList)
                sgfWr.setResult(game.winner, game.winReason)
                sgfWr.writeToFile(sgfFile, self.createdSgfDir)

            # update overall stats
            for engine in self.engines:
                engine.addGameResultToStats(game)

            # swap colors
            white, black = black, white

        # match end: print stats
        self._printMatchStats()

        # quit engines
        for engine in self.engines + [self.scorer]:
            if engine:
                engine.quit()

class Game:
    """ Plays games, scores them, and contains the game result & stats. """
    def __init__(self, whiteEngine, blackEngine, match):
        """ Initialize a Game object

        Arguments:
        whiteEngine - a ManagedEngine to play as W
        blackEngine - a ManagedEngine to play as B
        match - the Match to which the game belongs
        """
        self.whiteEngine = whiteEngine
        self.blackEngine = blackEngine
        self.match = match
        self.winner = None
        self.winReason = None
        self.numMoves = 0
        self.timeVioStr = None
        self.moveList = []

    def _scoreGame(self):
        """ Return (winner, winReason) with the score of the game acc/to scorer

        <Private use>

        Example return tuples: (WHITE, 5.5), (RESULT_JIGO, REASON_JIGO)
        Returns (RESULT_NONE, REASON_NONE) if match has no scorer assigned or if
        there was a problem.
        """
        scr = self.match.scorer
        if scr:
            try:
                if scr is self.whiteEngine or scr is self.blackEngine:
                    score = scr.finalScore()
                else:
                    score = scr.scoreFromMoveList(self.moveList)
            except GtpCannotScore as e:
                msg = 'Could not score game. Refusal from {0}:'
                printErr(msg.format(scr.name), sub=e)
                return RESULT_NONE, REASON_SCOR
            except GtpException as e:
                msg = 'Could not score game. GTP error from {0}:'
                printErr(msg.format(scr.name), sub=e)
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
            msg = '\nCould not score game. Bad score format from {0}:'
            printErr(msg.format(scr.name), sub=score)
            return RESULT_NONE, REASON_SCOR
        return RESULT_NONE, REASON_NONE

    def play(self):
        """ Play the game, set winner, winReason, numMoves, timeVioStr, moveList
        """
        assert not (self.winner or self.winReason
                    or self.timeVioStr or self.moveList)
        assert self.numMoves == 0

        consecPasses = 0

        # clear engine boards & stats
        coleng = {WHITE: self.whiteEngine, BLACK: self.blackEngine}
        for (col, eng) in coleng.items():
            while True:
                try:
                    eng.newGame(col)
                    break
                except:
                    eng.restart() # will abort match after several tries

        mover = self.blackEngine # mover moves; start with black
        placer = self.whiteEngine # placer just places move generated by mover

        while True:
            # play a move
            if mover.moveWait: time.sleep(mover.moveWait)
            try:
                (move, isTimeViolation, delta) = mover.timedMove()
            except GtpException as e: #TODO distinguish diff GTP exceptions
                msg = 'GTP error with {0}:'
                printErr(msg.format(mover.name), sub=e)
                mover.restart() # has a limit, so we won't hang
                self.winner, self.winReason = RESULT_ERR, REASON_ERR
                return

            # end game if time exceeded and enforceTime=1, only log otherwise
            if isTimeViolation:
                violator = '{name} {m}[{s}]'.format(
                            name=mover.name,
                            m=self.numMoves + 1,
                            s=delta.total_seconds())
                if not self.timeVioStr:
                    self.timeVioStr = violator
                else:
                    self.timeVioStr += ', ' + violator
                if self.match.enforceTime:
                    self.winner, self.winReason = placer.color, REASON_TIME
                    return

            # end game if resigned
            if move.lower() == 'resign':
                self.winner, self.winReason = placer.color, REASON_RESIGN
                return

            # move is not resign or invalidated by time controls enforcement
            self.moveList.append(move)
            self.numMoves+=1

            #  passes / try to score game if consecutive passes > config val
            consecPasses = consecPasses + 1 if move.lower() == 'pass' else 0
            if consecPasses >= self.match.consecPassesToEnd:
                self.winner, self.winReason = self._scoreGame()
                return

            # place move on opponent board
            try:
                placer.placeOpponentStone(move)
            except GtpIllegalMove as e:
                self.winner, self.winReason = RESULT_UFIN, REASON_ILM
                msg = 'Match {0}: {1} does not like a move'
                printErr(msg.format(self.match.name, placer.name), sub=e)
                return
            except GtpException as e:
                msg = 'GTP error with {0}'
                printErr(msg.format(placer.name), sub=e)
                placer.restart()
                # few more tries
                self.winner, self.winReason = RESULT_ERR, REASON_ERR
                return


            mover, placer = placer, mover

class DumbarbConfig:
    """ Reads in the config file and provides access to config values. """
    def __init__(self):
        """ Initialize object containing all the config values

        Uses argparse to read command line parameters, including config file(s),
        then parses the config files as well.
        """
        args = self._parseArgs()

        self.config = configparser.ConfigParser(inline_comment_prefixes='#',
                    empty_lines_in_values=False)
        self.config.SECTCRE = re.compile(r'\[ *(?P<header>[^]]+?) *\]')
        try:
            readFiles = self.config.read(args.configFile)
        except configparser.Error as e:
            msg = 'Problem reading config file(s):'
            raise ConfigError(msg, sub=e)

        sections = self.config.sections()
        self.matchSections = [x for x in sections if ' ' in x]
        self.engineSections = [x for x in sections if ' ' not in x]

        if not self.matchSections:
            msg = 'No match sections found in config file(s)'
            raise ConfigError(msg, sub=args.configFile)

        # check that keys are valid in all sections (inc. DEFAULT)
        for sec in self.config.keys():
            keys = self.config[sec].keys()
            if not keys <= INI_KEYSET:
                msg = 'Invalid keyword(s) in config file(s):'
                raise ConfigError(msg, sub=keys - INI_KEYSET)

        # from args
        self.startWith = args.start_with
        self.showDiagnostics = not args.quiet
        self.showDebug = args.debug
        self.showProgress = not args.quiet and not args.no_indicator
        self.gtpDebug = args.gtp_debug

    def __getitem__(self, key):
        """ Provide access to config file sections (engine/match defs) """
        try:
            key = self.config[key]
        except KeyError as e:
            msg = 'Could not find section for engine {0}'
            raise ConfigError(msg.format(e)) from None
        return key

    @staticmethod
    def _parseArgs():
        """ Parse command line arguments and return an ArgumentParser

        <Private use>
        """
        blurb = '''
        Copyright (C) 2017 Stanislav Traykov
        License: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
        This is free software: you are free to change and redistribute it.
        There is NO WARRANTY, to the extent permitted by law.
        '''
        argParser = argparse.ArgumentParser(
                    description='Run matches between GTP engines.',
                    formatter_class=argparse.RawDescriptionHelpFormatter)
        argParser.add_argument('configFile',
                    nargs='+',
                    metavar='<config file>',
                    type=str,
                    help='Configuration file')
        argParser.add_argument('-I', '--no-indicator',
                    action='store_true',
                    help='Disable progress indicator')
        argParser.add_argument('-n', '--start-with',
                    metavar='<start no>',
                    type=int, default=1,
                    help='Start with this game number (default 1)')
        argParser.add_argument('-q', '--quiet',
                    action='store_true',
                    help='Quiet mode: nothing except critical messages')
        argParser.add_argument('-d', '--debug',
                    action='store_true',
                    help='Show extra diagnostics')
        argParser.add_argument('-g', '--gtp-debug',
                    action='store_true',
                    help='Show GTP commands/responses')
        argParser.add_argument('-c', '--continue',
                    action='store_true',
                    help='Continue an interrupted session')
        argParser.add_argument('-v', '--version',
                    action='version',
                    version='{0} {1}\n{2}'.format(
                                DUMBARB, DUMBVER, textwrap.dedent(blurb)))
        return argParser.parse_args()

################################### function ###################################

def printErr(message='', end='\n', flush=True, prefix='<ARB> ',
                sub=None, skipformat=False):
    """ Print a message to stderr, thread-safe and magic-performing

    If the last thing printed did not have a newline (e.g. indicator dot),
    printErr will prepend a newline.

    Arguments:
    message -- the message to print (default '')
    end -- an optional termination string (default '\n')
    flush -- whether to flush the buffer (default True)
    prefix -- prefix messages with this (default '<ARB> ')
    sub -- secondary message that will be specially indented (default None)
    skipformat -- skip formatting magic; no end, no prefix (default False)
    """
    end = '' if skipformat else str(end)
    prefix = '' if skipformat else str(prefix)
    sub = '\n' + textwrap.indent(str(sub).rstrip(), str(prefix) + '   ') if sub else ''
    with printErr.globalLock:
        prepend = '' if skipformat or printErr.lastPrintNL else '\n'
        outmessage = prepend + prefix + str(message) + sub + end
        printErr.lastPrintNL = outmessage.endswith('\n')
        sys.stderr.write(outmessage)
        if flush: sys.stderr.flush()
# function object vars
printErr.globalLock = threading.Lock()
printErr.lastPrintNL = True

##################################### main #####################################

if __name__ == '__main__':
    try:
        cnf = DumbarbConfig()
    except ConfigError as e:
        printErr('Config error:', sub=e)
        sys.exit(125)

    aborted = 0
    for s in cnf.matchSections:
        try:
            with Match(s, cnf) as m: # best effort to end processes, close fds
                m.play()

        except (ConfigError, GtpException, MatchAbort,
                        OSError, ValueError) as e:
            msg = 'Match [{0}] aborted ({1}):'
            printErr(msg.format(s, e.__class__.__name__), sub=e)
            if cnf.showDebug:
                trfmt = traceback.format_exception(*sys.exc_info())
                printErr(sub=''.join(trfmt))

            aborted += 1
            continue
        except AllAbort as e:
            printErr('Something bad happened. Aborting all matches.', sub=e)

    sys.exit(max(120, aborted))
