# !/usr/bin/env python3
"""
                   dumbarb, the dumb GTP arbiter
   Copyright (C) 2017 Stanislav Traykov st-at-gmuf-com / GNU GPL3

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

See https://github.com/StanTraykov/dumbarb for more info
"""

import argparse, configparser
import datetime, os, shlex, string, subprocess, sys, time

# config constants -- you may want to change these:

DUMBARB = 'dumbarb'
DUMBVER = '0.2.0'

FMT_PRERE = '[{seqno:0{swidth}}] {name1} {col1} {name2} {col2} = '
FMT_WIN_W = '{name:>{nwidth}} W+'
FMT_WIN_B = '{name:>{nwidth}} B+'
FMT_JIGO  = '{jigo:>{nwidth}}   '
FMT_RSERR = '{none:>{nwidth}}   '
FMT_REST  = (
            '{reason:6} {moves:3} {mv1:3} {mv2:3}'
            ' {tottt1:11.6f} {avgtt1:9.6f} {maxtt1:9.6f}'
            ' {tottt2:11.6f} {avgtt2:9.6f} {maxtt2:9.6f}'
            ' VIO: {vio}'
            )

JIGO     = 'Jigo'
RES_NONE = 'None' # used for result None and violations None
WAITQUIT = 5      # seconds to wait for engine to exit before killing process

# non-config constants -- you probably don't want to change these:

R_RESIGN = 'Resign' # } used to produce proper SGF
R_TIME   = 'Time'   # }
BLACK = 'B' # } GTP and other stuff relies on these values
WHITE = 'W' # }

class SGF:
    """ Stores SGF data and can write it to a file. """
    SGF_AP_VER = DUMBARB + ':' + DUMBVER
    SGF_BEGIN = ('(;GM[1]FF[4]CA[UTF-8]AP[{0}]RU[{1}]SZ[{2}]KM[{3}]GN[{4}]'
                'PW[{5}]PB[{6}]DT[{7}]EV[{8}]RE[{9}]\n')
    SGF_MOVE = ';{0}[{1}{2}]\n'
    SGF_END = ')\n'

    def writeToFile(self, dir=None):
        """ Write SGF to a file; filename = game name with spaces replaced by underscore.

        Keyword arguments:
        dir -- directory to place file in (default = None = write to cwd)
        """
        assert self.result != None, 'Attempt to write SGF with unknown result'
        fileName = self.gameName.replace(' ', '_') + '.sgf'
        if dir != None:
            fileName = os.path.join(dir, fileName)
        with open(fileName, 'w', encoding='utf-8') as file:
            begin = self.SGF_BEGIN.format(self.SGF_AP_VER, # 0 AP
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
            file.write(self.SGF_END)

    def addMove(self, coord):
        """ Add a move to the SGF data, adding today's date to the SGF date string.

        Arguments:
        coord -- the board coordinates in GTP notation
        """
        todayIso = datetime.datetime.now().date().isoformat()
        if todayIso not in self.datesIso: self.datesIso += ',' + todayIso

        color = BLACK if self.blacksTurn else WHITE
        if coord.lower() == 'pass':
            letterLtoR = ''
            letterTtoB = ''
        else:
            assert len(coord) <= 3, (
                        'SGF.addMove got something other than pass/coords: {0}'.format(coord))
            idxLtoR = string.ascii_lowercase.index(coord[0].lower())
            # GTP skips i, SGF doesn't, so reduce by 1 from j (9) onwards
            if idxLtoR > 8: idxLtoR -= 1
            idxTtoB = abs(int(coord[1:])-self.gameSettings.boardSize)
            letterLtoR = string.ascii_lowercase[idxLtoR]
            letterTtoB = string.ascii_lowercase[idxTtoB]
        mvString = self.SGF_MOVE.format(color, letterLtoR, letterTtoB)
        self.movesString += mvString
        self.blacksTurn = not self.blacksTurn

    def setResult(self, winner, plusText=None):
        """ Add the game result to the SGF data.

        Arguments:
        winner -- one of the constants WHITE, BLACK or JIGO, specifying the winner or jigo
        plusText -- the text after + if result is not jigo: Resign, Time, or score difference
                    (default None)
        """
        if winner == WHITE:
            self.result = 'W+' + plusText
        elif winner == BLACK:
            self.result = 'B+' + plusText
        elif winner == JIGO:
            self.result = '0' #SGF for jigo
        else:
            self.result = '?' #SGF for 'unknown result'

    def __init__(self, gameSettings, whiteName, blackName, gameName, eventName):
        """ Construct an SGF object.

        Arguments:
        gameSettings -- a GameSettings object containing the game settings
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

class GameSettings:
    """ Holds go game settings (board size, komi, time settings). """
    def usingNoTimeControls(self):  return self.timeSys == 0
    def usingAbsoluteTime(self):    return self.timeSys == 1
    def usingCanadianByoYomi(self): return self.timeSys == 2
    def usingJapaneseByoYomi(self): return self.timeSys == 3
    def __init__(self, boardSize=19, komi=7.5, mainTime=0, periodTime=5, periodCount=1, timeSys=2):
        """ Construct a GameSettings object.

        Arguments:
        boardSize = size of the board (default 19)
        komi = komi (default 7.5)
        mainTime = main time in seconds (default 0)
        periodTime = period time in seconds (default 5)
        periodCount = period count (Japanese) / stone count per period (Canadian) (default 1)
        timeSys = time system: 0=none, 1=absolute time, 2=canadian, 3=japanese byoyomi (default 2)
        """
        self.boardSize = boardSize
        self.komi = komi
        self.mainTime = mainTime
        self.periodTime = periodTime
        self.periodCount = periodCount
        self.timeSys = timeSys

class GTPEngine:
    """ Provides an interface to a GTP engine and some helper functions."""
    gtpDebug = False

    def _errMessage(self, message):
        """Write an error message to stderr and flush."""
        sys.stderr.write(message)
        sys.stderr.flush()

    def _rawRecvResponse(self, exitOnError=True):
        """Receive a GTP response, decode it, and return it with trailing whitespace removed.

        Can return False if there was an error and it was called with exitOnError=False.

        Arguments:
        exitOnError -- whether to exit upon encountering an OS error when reading (default True)
        """
        responseBytes = b''
        while True:
            try:
                line = self.eout.readline()
            except OSError:
                if exitOnError:
                    self._errMessage("Can't receive response from engine.\n")
                    sys.exit(1)
                else:
                    return None
            if responseBytes != b'' and (line == b'\n' or line == b'\r\n'):
                break # break if empty line encountered (unless it is first thing)
            responseBytes += line
        response=responseBytes.decode().rstrip()
        if self.gtpDebug:
            if self.name != None:
                self._errMessage('[{0}] '.format(self.name))
            self._errMessage('Received: ' + response + '\n')
        return response

    def _rawSendCommand(self, command, exitOnError=True):
        """Send a GTP command and return True; encode and ensure proper newline termination.

        Can return False if there was an error and it was called with exitOnError=False.

        Arguments:
        command -- a string containing the GTP command and any arguments
        exitOnErr -- whether to exit upon encountering and OS err when writing (default True)
        """
        if self.gtpDebug:
            if self.name != None:
                self._errMessage('[{0}] '.format(self.name))
            self._errMessage('Sending: ' + command + '\n')
        try:
            self.ein.write(command.rstrip().encode() + b'\n')
        except OSError:
            if exitOnError:
                self._errMessage("Can't send command to engine.\n")
                sys.exit(1)
            else:
                return False
        if command.lower().strip() == 'quit':
            self.quit = True
        return True

    def sendCommand(self, command):
        """ Send a GTP command that generates no output. Receive the (empty) response.

        Arguments:
        commmand -- a string containing the GTP command and its arguments (if any)
        """
        self._rawSendCommand(command)
        response = self._rawRecvResponse()
        assert response == '=', 'GTP error: "{0}"'.format(response)

    def getResponseFor(self, command):
        """ Send a GTP command that generates output. Receive its output and return it.

        Arguments:
        command -- a string containing the GTP command and its arguments (if any)
        """
        self._rawSendCommand(command)
        response = self._rawRecvResponse()
        assert response [:2] == '= ', 'GTP error: "{0}"'.format(response)
        return response[2:]

    def timeLeft(self, timeLeftArguments):
        """ Send the GTP time_left command with the supplied arguments.

        Arguments:
        timeLeftArguments -- the arguments to the GTP time_left command
        """
        assert self.color == BLACK or self.color == WHITE, (
                    'Invalid color: {0}'.format(self.color))
        self.sendCommand('time_left {0} {1}'.format(self.color, timeLeftArguments))

    def move(self):
        """ Return a generated move from the engine (in GTP notation). """
        assert self.color == BLACK or self.color == WHITE, (
                    'Invalid color: {0}'.format(self.color))
        return self.getResponseFor('genmove ' + self.color)

    def finalScore(self):
        """ Return the final score as assessed by the engine. """
        return self.getResponseFor('final_score')

    def placeOpponentStone(self, coord):
        """ Place a stone of the opponent's color on the engine's board.

        Arguments:
        coord -- the board coordinates in GTP notation
        """
        assert self.color == BLACK or self.color == WHITE, (
                    'Invalid color: {0}'.format(self.color))
        if self.color == BLACK:
            oppColor = WHITE
        else:
            oppColor = BLACK
        return self.sendCommand('play {0} {1}'.format(oppColor, coord))

    def playMoveList(self, moveList, firstColor=BLACK):
        """ Place stones with alternating colors on the coordinates given in moveList.

        Arguments:
        moveList -- list of strings containing board coordinates in GTP notation
        firstColor -- one of the constants BLACK or WHITE: start with this color (default BLACK)
        """
        color = firstColor
        for move in moveList:
            self.sendCommand('play {0} {1}'.format(color, move))
            color = WHITE if color == BLACK else BLACK

    def clear(self):
        """ Clear the engine's board in preparation of a new game."""
        self.sendCommand('clear_board')

    def gameSetup(self, settings):
        """ Issue a number of GTP commands setting up game parameters.

        Used to set up board size, komi, time system and time settings. The Japanese byo yomi
        time system requires engine support of the GTP extension command kgs-time_settings.

        Arguments:
        settings -- a GameSettings object containing the game settings
        """
        m = settings.mainTime
        p = settings.periodTime
        c = settings.periodCount
        self.sendCommand('boardsize ' + str(settings.boardSize))
        self.sendCommand('komi ' + str(settings.komi))
        if settings.usingJapaneseByoYomi():
            self.sendCommand('kgs-time_settings byoyomi {0} {1} {2}'.format(m, p, c))
        else:
            if settings.usingAbsoluteTime():
                p = 0 # GTP convention for abs time (=0)
            elif settings.usingNoTimeControls():
                p = 1 # GTP convention for no time sys (>0)
                c = 0 # GTP convention for no time sys (=0)
            self.sendCommand('time_settings {0} {1} {2}'.format(m, p, c))

    def beWhite(self):
        """ Sets the color for the engine to white. """
        if self.gtpDebug and self.name != None:
            self._errMessage('[{0}] * now playing as White\n'.format(self.name))
        self.color = WHITE

    def beBlack(self):
        """ Sets the color for the engine to black. """
        if self.gtpDebug and self.name != None:
            self._errMessage('[{0}] * now playing as Black\n'.format(self.name))
        self.color = BLACK

    def scoreFromMoveList(self, settings, moveList):
        """ Returns the engine's score assessment for a game by placing all the stones first.

        This just calls the methods clear(), gameSetup(settings), playMoveList(moveList) and returns
        finalScore().

        Arguments:
        settings -- a GameSettings object containing the game settings (such as komi and board size)
        moveList -- a list of strings containing board coordinates in GTP notation
        """
        self.clear()
        self.gameSetup(settings)
        self.playMoveList(moveList)
        return self.finalScore()

    @classmethod
    def fromCommandLine(cls, cmdLine, name=None):
        """ Return a GTPEngine object from a supplied command line (creating a child process).

        The child process is stored in the GTPEngine object and some house-keeping is performed,
        if the object gets deleted, such as sending a GTP 'quit' (if it wasn't sent already),
        waiting for the child process to terminate, and killing it, if it doesn't in time.

        Arguments:
        cmdLine -- command line for the engine
        name -- the engine name for logging/display purposes (default None)
        """
        windows = sys.platform.startswith('win')
        if (windows):
            cmdArgs = cmdLine
        else:
            cmdArgs = shlex.split(cmdLine)

        # do not use Popen cwd param: does not seem to reliably search for executable in cwd
        # rely on caller manually changing dir, if they want cwd
        p = subprocess.Popen(cmdArgs, bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
        return cls(process=p, name=name)

    def __init__(self, ein=None, eout=None, process=None, name=None):
        """ Construct a GTPEngine object from EITHER two streams (ein and eout) OR a Popen object.

        Arguments:
        ein -- engine input stream (default None)
        eout -- engine output stream (default None)
        process -- a subprocess.Popen object (running child process) (default None)
        name -- the engine name for logging/display purposes (default None)
        """
        self.subProcess = process
        if process == None:
            assert ein != None and eout != None
            self.ein = ein
            self.eout = eout
        else:
            assert ein == None and eout == None
            self.ein = process.stdin
            self.eout = process.stdout
        self.name = name
        self.color = None
        self.quit = False

    def __del__(self):
        """ Send 'quit' to the engine (if needed), wait for child process or kill on timeout."""
        if self.subProcess != None:
            if not self.quit:
                try:
                    self._rawSendCommand('quit', False)
                    response = self._rawRecvResponse(False)
                except OSError:
                    self._errMessage("Couldn't quit child.\n")
            try:
                self.subProcess.wait(WAITQUIT)
            except subprocess.TimeoutExpired:
                self.subProcess.kill()

class GameResult: # returned by playGame
    """ Stores the result of a game with some addtional data we want to keep."""
    def __init__(self, winner, reason, numMoves, timeVio):
        """ Constructs a GameResult object.

        Arguments:
        winner = one of the constants WHITE or BLACK or JIGO specifying the winner/result
        reason = the reason or score (the text after '+'' in W+Resign, W+Time, B+3.5)
        numMoves = number of moves for the game (excluding the final 'resign' move, if any)
        timeVio = a string containing all the time violations in format 'engine move[time], ...'
        """
        self.winner = winner
        self.reason = reason
        self.numMoves = numMoves
        self.timeVio = timeVio

class DumbarbConfig:
    """ Reads in the config file and provides access to config values. """
    def __init__(self, configFile):
        """ Constructs a DumbarbConfig object containing all the config values.

        Arguments:
        configFile -- the name of the config file
        """
        config = configparser.ConfigParser(inline_comment_prefixes='#')
        config.read(configFile)
        self.engineNames = config.sections()
        self.config = config
        assert len(self.engineNames) == 2 # DEFAULT section not counted

        # config vars in DEFAULT section
        self.numGames = int(config['DEFAULT'].get('numGames', 100))
        self.periodTime = int(config['DEFAULT'].get('periodTime', 2))
        self.sgfDir = config['DEFAULT'].get('sgfDir', None)
        self.boardSize = int(config['DEFAULT'].get('boardSize', 19))
        self.komi = float(config['DEFAULT'].get('komi', 7.5))
        self.mainTime = int(config['DEFAULT'].get('mainTime', 0))
        self.periodCount = int(config['DEFAULT'].get('periodCount', 1))
        self.timeSys = int(config['DEFAULT'].get('timeSys', 2))
        self.consecPasses = int(config['DEFAULT'].get('consecutivePasses', 2))
        self.initialWait = float(config['DEFAULT'].get('initialWait', 0.5))
        self.moveWait = float(config['DEFAULT'].get('moveWait', 0))
        self.enforceTime = int(config['DEFAULT'].get('enforceTime', 0)) > 0
        self.timeTolerance = float(config['DEFAULT'].get('timeTolerance', 0))
        self.scorer = config['DEFAULT'].get('scorer', None)
        self.scorerWkDir = config['DEFAULT'].get('scorerWkDir', None)

    def __getitem__(self, key):
        """Magic method providing accesss to the engine sections of the config file. """
        return self.config[key]

class TimeKeep:
    """ Stores game settings and common time stats, performs time checks.

    Time stats specific to one engine are stored with the GTPEngine object as some extra attributes
    but are set/accessed only from this class.
    """
    def updateEngineStats(self, engine, gameRes):
        """Update the stats array of an engine with the game result supplied in gameRes

        Arguments:
        gameRes -- a GameResult object containing the game result
        maxTimeTaken -- a datetime.timedelta object containing the max time per 1 move for the game
        """
        assert engine.color == BLACK or engine.color == WHITE, (
                    'Invalid color: {0}'.format(engine.color))

        # create stats array, if it doesn't exist
        if not hasattr(engine, 'stats'):
            engine.stats = [0, 0, 0, 0, 0, 0, 0]

        # update games won/totals:
        engine.stats[1] += 1 # total games
        if engine.color==WHITE:
            engine.stats[3] += 1 # total as W
            if gameRes.winner==WHITE:
                engine.stats[0] += 1 # total wins
                engine.stats[2] += 1 # wins as W
        else: # engine is BLACK
            engine.stats[5] += 1 # total as B
            if gameRes.winner==BLACK:
                engine.stats[0] += 1 # total wins
                engine.stats[4] += 1 # wins as B

        # update max time/move overall
        maxtt = engine.maxTimeTaken.total_seconds()
        if maxtt > engine.stats[6]: engine.stats[6] = maxtt # max t/move for match

    def checkinDelta(self, engine, delta):
        """ Check in a new move, update engine timers, return whether time controls violated.

        This method is used to

        Arguments:
        engine -- a GTPEngine object
        delta -- a timedate.delta object containing the move delta (the time spent on a move)
        """
        engine.totalTimeTaken += delta
        if delta > engine.maxTimeTaken: engine.maxTimeTaken = delta

        if self.settings.usingNoTimeControls() or self.timeTolerance < 0:
            return False

        if self.settings.usingAbsoluteTime():
            timeLeft = self.mainTime - engine.totalTimeTaken.total_seconds()
            engine.GTPTimeLeft = '{0} 0'.format(int(timeLeft) if timeLeft > 0 else 0)
            return timeLeft + self.timeTolerance > 0

        if not engine.inByoyomi:
            overMain = engine.totalTimeTaken.total_seconds() - self.settings.mainTime
            if overMain < 0:
                engine.GTPTimeLeft = '{0} 0'.format(int(-overMain))
                return False # still in main time
            # starting byo yomi
            engine.inByoyomi = True
            delta = datetime.timedelta(seconds = overMain)

        if self.settings.usingJapaneseByoYomi():
            exhaustedPeriods = int(delta.total_seconds() / self.settings.periodTime)
            if exhaustedPeriods >= engine.periodsLeft:
                deltaWithTolerance = max(0, delta.total_seconds() - self.timeTolerance)
                exhaustedPeriods = int(deltaWithTolerance / self.settings.periodTime)
            engine.periodsLeft -= exhaustedPeriods
            engine.GTPTimeLeft = '{0} {1}'.format(
                        self.settings.periodTime,
                        engine.periodsLeft if engine.periodsLeft > 0 else 1)
            return engine.periodsLeft <= 0

        if self.settings.usingCanadianByoYomi():
            engine.periodTimeLeft-=delta.total_seconds()
            if engine.periodTimeLeft + self.timeTolerance < 0:
                violation=True
            else:
                violation=False
            engine.stonesLeft -= 1
            if engine.stonesLeft == 0:
                engine.stonesLeft = self.settings.periodCount
                engine.periodTimeLeft = self.settings.periodTime
                engine.GTPTimeLeft = '{0} {1}'.format(engine.periodTimeLeft, engine.stonesLeft)
            else:
                engine.GTPTimeLeft = '{0} {1}'.format(
                    int(engine.periodTimeLeft) if engine.periodTimeLeft > 0 else 0,
                    engine.stonesLeft)
            return violation

        return True #don't know this timeSys; fail

    def resetEngineTimeStats(self, engine):
        """ Reset time stat attributes of GTPEngine in preparation of a new game.

        Arguments:
        engine -- the GTPEngine to be reset
        """
        s = self.settings
        if not s.usingNoTimeControls():
            if s.mainTime > 0:
                engine.GTPTimeLeft = '{0} 0'.format(s.mainTime)
            else:
                engine.GTPTimeLeft = '{0} {1}'.format(s.periodTime, s.periodCount)
        else:
            engine.GTPTimeLeft = None
        engine.maxTimeTaken = datetime.timedelta()
        engine.totalTimeTaken = datetime.timedelta()
        engine.periodsLeft = s.periodCount if s.usingJapaneseByoYomi() else None
        engine.stonesLeft  = s.periodCount if s.usingCanadianByoYomi() else None
        engine.periodTimeLeft = s.periodTime if s.usingCanadianByoYomi() else None
        engine.inByoyomi = False

    def __init__(self, settings,
                    timeTolerance, enforceTime, moveWait, consecPasses):
        """ Constructs a TimeKeep object.

        Arguments:
        settings -- a GameSettings object containing the game settings
        timeTolerance -- time tolerance in seconds (microsecond precision)
        enforceTime -- True if engines should lose by time, False if violations should only be
                       logged
        moveWait -- time to wait between moves (seconds)
        consecPassess -- number of consecutive passes for game to end
        """
        self.settings = settings
        self.timeTolerance = timeTolerance
        self.enforceTime = enforceTime
        self.moveWait = moveWait
        self.consecPasses = consecPasses

def printErr(message, end='\n', flush=True):
    """ Print a message to stderr.

    Arguments:
    message -- the message string
    end -- terminate the message with this string (default '\n')
    flush -- flush the buffer (default True)
    """
    sys.stderr.write(message + end)
    if flush: sys.stderr.flush()

def printOut(message, end='\n', flush=True):
    """ Print a message to stdout.

    Arguments:
    message -- the message string
    end -- terminate the message with this string (default '\n')
    flush -- flush the buffer (default True)
    """
    sys.stdout.write(message + end)
    if flush: sys.stdout.flush()

# has the engines play a game, returns GameResult
def playGame(whiteEngine, blackEngine, tk, scrEngine, sgf):
    """ Play a game between two engines.

    Arguments:
    whiteEngine -- the GTPEngine to take white
    blackEngine -- the GTPEngine to take black
    tk -- the TimeKeep object
    scrEngine -- the GTPEngine to peform scoring (can be None)
    sgf -- a SGF object
    """
    timeVioStr = None
    consecPasses = 0
    numMoves = 0
    moveList = []
    whiteEngine.beWhite()
    blackEngine.beBlack()

    # clear engine boards & stats
    for engine in (whiteEngine, blackEngine):
        engine.clear()
        tk.resetEngineTimeStats(engine)
        engine.movesMade=0

    mover=blackEngine # mover moves; start with black (GTP genmove)
    placer=whiteEngine # placer just places move generated by mover (GTP play)

    while True:
        if tk.moveWait > 0: time.sleep(tk.moveWait)
        if tk.timeTolerance >= 0 and not tk.settings.usingNoTimeControls():
            mover.timeLeft(mover.GTPTimeLeft)
        beforeMove = datetime.datetime.utcnow()
        move = mover.move()
        delta = datetime.datetime.utcnow() - beforeMove
        mover.movesMade += 1 # increments on resign & timeout-enforced move, unlike numMoves
        moveList.append(move)
        timeViolation = tk.checkinDelta(mover, delta)

        if timeViolation:
            violator = '{name} {m}[{s}]'.format(
                        name=mover.name, m=numMoves + 1, s=delta.total_seconds())
            if timeVioStr == None:
                timeVioStr = violator
            else:
                timeVioStr += ', ' + violator
            if tk.enforceTime:
                return GameResult((WHITE if mover == blackEngine else BLACK),
                            R_TIME, numMoves, timeVioStr)

        if move.lower() == 'resign':
            return GameResult((WHITE if mover == blackEngine else BLACK),
                        R_RESIGN, numMoves, timeVioStr)

        if sgf != None: sgf.addMove(move)
        numMoves+=1

        if move.lower() == 'pass':
            consecPasses += 1
        else:
            consecPasses = 0

        if consecPasses >= tk.consecPasses:
            if scrEngine != None:
                if scrEngine == whiteEngine or scrEngine == blackEngine:
                    scoreString = scrEngine.finalScore()
                else:
                    scoreString = scrEngine.scoreFromMoveList(tk.settings, moveList)
                if scoreString != '0':
                    assert ((scoreString[0] == WHITE or scoreString[0] == BLACK)
                            and scoreString[1] == '+'), 'Invalid score: {0}'.format(scoreString)
                    winner =  scoreString[0]
                    points = scoreString[2:]
                    return GameResult(winner, points, numMoves, timeVioStr)
                else:
                    return GameResult(JIGO, '==', numMoves, timeVioStr)
            else:
                return GameResult(None, 'XX', numMoves, timeVioStr)

        placer.placeOpponentStone(move)
        mover, placer = placer, mover

def playMatch(engine1, engine2, numGames, tk, scrEngine, sgfDir):
    """ Play an n-game match between two engines.

    Arguments:
    engine 1 -- a GTPEngine object
    engine 2 -- a GTPEngine object
    numGames -- number of games to play
    tk -- a TimeKeep object
    scrEngine -- a GTPEngine to score games that did not end in resign or timeout (can be engine1,
                 engine2, a third engine, or None)
    sgfDir -- a directory to save SGF files in (or None to disable)
    """
    maxDgts=len(str(numGames)) # max # of digits for spacing of the game counter
    nWidth=max(len(engine1.name), len(engine2.name), len(JIGO), len(RES_NONE)) # name field in res

    printErr('Playing games: ', end='')

    # board settings
    for engine in (engine1, engine2):
        engine.gameSetup(tk.settings)

    white, black = engine1, engine2
    for i in range(numGames):
        # SGF prepare
        if sgfDir != None:
            sgf = SGF(tk.settings, white.name, black.name,
                        'game {0}'.format(i + 1), 'dumbarb {0}-game match'.format(numGames))
        else:
            sgf = None

        # play the game
        gameRes = playGame(white, black, tk, scrEngine, sgf)

        # print pre-result string
        printOut(FMT_PRERE.format(seqno = i + 1, swidth = maxDgts, nwidth = nWidth,
                    name1 = engine1.name, col1 = engine1.color,
                    name2 = engine2.name, col2 = engine2.color), end='', flush=False)

        # get/caluclate engine time stats
        engStats = []
        for engine in (engine1, engine2):
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
        if gameRes.winner == WHITE:
            printOut(FMT_WIN_W.format(name = white.name, nwidth = nWidth), end='', flush=False)
        elif gameRes.winner == BLACK:
            printOut(FMT_WIN_B.format(name = black.name, nwidth = nWidth), end='', flush=False)
        elif gameRes.winner == JIGO:
            printOut(FMT_JIGO.format(jigo = JIGO, nwidth = nWidth), end='', flush=False)
        else:
            printOut(FMT_RSERR.format(none = RES_NONE, nwidth= nWidth), end='', flush=False)
        printOut(FMT_REST.format(
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
                    moves = gameRes.numMoves,
                    reason = gameRes.reason if gameRes.reason != None else RES_NONE,
                    vio = gameRes.timeVio if gameRes.timeVio != None else RES_NONE,
                    nwidth = nWidth))
        printErr('.', end = '')

        # SGF write to file
        if sgfDir != None:
            sgf.setResult(gameRes.winner, gameRes.reason)
            sgf.writeToFile(sgfDir)

        # update overall stats
        for engine in (white, black):
            tk.updateEngineStats(engine, gameRes)

        # swap colors
        white, black = black, white

# ==================== main ====================

# read config
cnf = DumbarbConfig(sys.argv[1])

# settings / timekeep
settings = GameSettings(boardSize=cnf.boardSize, komi=cnf.komi, mainTime=cnf.mainTime,
            periodTime=cnf.periodTime, periodCount=cnf.periodCount, timeSys=cnf.timeSys)
tk = TimeKeep(settings, cnf.timeTolerance, cnf.enforceTime, cnf.moveWait, cnf.consecPasses)

# set up engines
startingWkDir = os.getcwd() #save starting working dir
engList = []
for engName in cnf.engineNames:
    assert len(engName.split()) == 1, 'Engine name should not contain whitespace'
    engWkDir = cnf[engName].get('wkDir', None)
    if engWkDir != None:
            os.chdir(engWkDir)
    e = GTPEngine.fromCommandLine(cnf[engName]['cmd'], engName)
    if engWkDir != None:
            os.chdir(startingWkDir) #change back before searching for next engine
    engList.append(e)

# set up scorer (if any)
scrEngine = None
if cnf.scorer != None:
    for engine in engList:
        if cnf.scorer == '[{0}]'.format(engine.name):
            scrEngine = engine
    if scrEngine == None:
        if cnf.scorerWkDir != None:
            os.chdir(cnf.scorerWkDir)
        scrEngine = GTPEngine.fromCommandLine(cnf.scorer, '<arb>')
        if cnf.scorerWkDir != None:
            os.chdir(startingWkDir)

# mkdir for SGF files
if cnf.sgfDir != None:
    createdSgfDir = cnf.sgfDir
    if os.path.exists(createdSgfDir):
        for i in range(1, 999):
            createdSgfDir = cnf.sgfDir + "-{0:03}".format(i)
            if not os.path.exists(createdSgfDir):
                printErr('"{0}" already exists; '
                            'storing SGFs in "{1}"'.format(cnf.sgfDir, createdSgfDir))
                break
    os.mkdir(createdSgfDir) # fails if 001-999 all exist

# run the actual match
assert len(engList) == 2
time.sleep(cnf.initialWait)
playMatch(engList[0], engList[1], cnf.numGames, tk, scrEngine, createdSgfDir)

# diagnostics to stderr
printErr('\nMatch ended. Overall stats:')
printErr('won games, total games, won as W, ttl as W, won as B, ttl as B, max time/move')
for eng in engList:
    printErr('{0}: {1}'.format(eng.name, eng.stats))
