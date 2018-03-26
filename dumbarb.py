#!/usr/bin/env python3
#                       dumbarb, the dumb GTP arbiter
#       Copyright (C) 2017 Stanislav Traykov st-at-gmuf-com / GNU GPL3

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

# See https://github.com/StanTraykov/dumbarb for more info

import configparser, datetime, os, shlex, string, subprocess, sys, time

DUMBARB = "dumbarb"
DUMBVER = "0.1.4"

FMT_PRERESULT = "[{seqno:0{swidth}}] {white:{nwidth}} WHITE vs {black:{nwidth}} BLACK = "
FMT_WIN_W = "{name:{nwidth}} WIN WHITE ; "
FMT_WIN_B = "{name:{nwidth}} WIN BLACK ; "
FMT_REST = ("TM: {name1:{nwidth}} {maxtt1:9.6f} {tottt1:9.6f} {avgtt1:12.9f} "
                "{name2:{nwidth}} {maxtt2:9.6f} {tottt2:9.6f} {avgtt2:12.9f}"
                " ; MV: {moves:3} +{reason:6} VIO: {vio}")

R_RESIGN = "Resign" # } don't change: used in SGF output
R_TIME = "Time"     # }

class SGF:
    SGF_AP_VER = DUMBARB + ':' + DUMBVER
    SGF_BEGIN = ("(;GM[1]FF[4]CA[UTF-8]AP[{0}]RU[{1}]SZ[{2}]KM[{3}]GN[{4}]"
                "PW[{5}]PB[{6}]DT[{7}]EV[{8}]RE[{9}]\n")
    SGF_MOVE = ";{0}[{1}{2}]\n"
    SGF_END = ")\n"

    def writeToFile(self, dir=None):
        assert self.result != None, "Attempt to write SGF with unknown result"
        fileName = self.gameName.replace(" ", "_") + ".sgf"
        if dir != None:
            fileName = os.path.join(dir, fileName)
        with open(fileName, 'w', encoding='utf-8') as file:
            begin = self.SGF_BEGIN.format(self.SGF_AP_VER, #0 AP
                            "Chinese", #1 RU
                            self.gameSettings.boardSize, #2 SZ
                            self.gameSettings.komi, #3 KM
                            self.gameName, #4 GN
                            self.whiteName, #5 PW
                            self.blackName, #6 PB
                            self.datesIso, #7 DT
                            self.eventName, #8 EV
                            self.result) #9 RE
            file.write(begin)
            file.write(self.movesString)
            file.write(self.SGF_END)

    def addMove(self, coord): #gets GTP style coords
        todayIso = datetime.datetime.now().date().isoformat()
        if todayIso not in self.datesIso: self.datesIso += ',' + todayIso
        if self.blacksTurn: color = 'B'
        else:               color = 'W'
        if coord.lower() == 'pass':
            letterLtoR = ""
            letterTtoB = ""
        else:
            assert len(coord) <= 3, (
                        "SGF.addMove got something other than pass/coords: {0}".format(coord))
            idxLtoR = string.ascii_lowercase.index(coord[0].lower())
            if idxLtoR > 8: idxLtoR -= 1 #GTP skips i, SGF doesn't, so reduce by 1 from j onwards
            idxTtoB = abs(int(coord[1:])-self.gameSettings.boardSize)
            letterLtoR = string.ascii_lowercase[idxLtoR]
            letterTtoB = string.ascii_lowercase[idxTtoB]
        mvString = self.SGF_MOVE.format(color, letterLtoR, letterTtoB)
        self.movesString += mvString
        self.blacksTurn = not self.blacksTurn

    def setResult(self, whiteWon, plusText):
        if whiteWon:
            self.result = "W+" + plusText
        else:
            self.result = "B+" + plusText

    def __init__(self, gameSettings, whiteName, blackName, gameName, eventName):
        self.datesIso = datetime.datetime.now().date().isoformat()
        self.result = None
        self.blacksTurn = True
        self.movesString = ""
        self.gameSettings = gameSettings
        self.whiteName = whiteName
        self.blackName = blackName
        self.gameName = gameName
        self.eventName = eventName

class GameSettings:
    def usingNoTime(self):   return self.timeSys == 0
    def usingAbsolute(self): return self.timeSys == 1
    def usingCanadian(self): return self.timeSys == 2
    def usingByoyomi(self):  return self.timeSys == 3
    def __init__(self, boardSize=19, komi=7.5, mainTime=0, periodTime=5, periodCount=1, timeSys=2):
        self.boardSize = boardSize
        self.komi = komi
        self.mainTime = mainTime
        self.periodTime = periodTime
        self.periodCount = periodCount
        self.timeSys = timeSys

class GTPEngine:
    BLACK = 'B'
    WHITE = 'W'
    gtpDebug = False

    def _errMessage(self, message):
        sys.stderr.write(message)
        sys.stderr.flush()

    def _rawRecvResponse(self):
        responseBytes = b''
        while True:
            line = self.eout.readline()
            if responseBytes != b'' and (line == b'\n' or line == b'\r\n'):
                break # break if empty line encountered (unless it is first thing)
            responseBytes += line
        response=responseBytes.decode().rstrip()
        if self.gtpDebug:
            if self.name != None:
                self._errMessage("[{0}] ".format(self.name))
            self._errMessage("Received: " + response + '\n')
        return response

    def _rawSendCommand(self, command):
        if self.gtpDebug:
            if self.name != None:
                self._errMessage("[{0}] ".format(self.name))
            self._errMessage("Sending: " + command + '\n')
        self.ein.write(command.encode() + b'\n')
        if command.lower().strip() == 'quit':
            self.quit = True

    def sendCommand(self, command): #send command without output (like boardsize, play)
        self._rawSendCommand(command)
        response = self._rawRecvResponse()
        assert response == '=', "GTP error: '{0}'".format(response)
        return

    def getResponseFor(self, command): #send command and receive its output (like genmove)
        self._rawSendCommand(command)
        response = self._rawRecvResponse()
        assert response [:2] == '= ', "GTP error: '{0}'".format(response)
        return response[2:]

    def move(self): #return a generated move (GTP genmove)
        assert self.color == self.BLACK or self.color == self.WHITE, (
                    "Invalid color: {0}".format(self.color))
        return self.getResponseFor("genmove " + self.color)

    def placeOpponentStone(self, coord): #place an opponent's stone on the board (GTP play)
        assert self.color == self.BLACK or self.color == self.WHITE, (
                    "Invalid color: {0}".format(self.color))
        if self.color == self.BLACK:    oppColor = self.WHITE
        else:                           oppColor = self.BLACK
        return self.sendCommand("play {0} {1}".format(oppColor, coord))

    def clear(self): #clear the board
        self.sendCommand("clear_board")

    def gameSetup(self, settings):
        m = settings.mainTime
        p = settings.periodTime
        c = settings.periodCount
        self.sendCommand("boardsize " + str(settings.boardSize))
        self.sendCommand("komi " + str(settings.komi))
        if settings.usingByoyomi():
            self.sendCommand("kgs-time_settings byoyomi {0} {1} {2}".format(m, p, c))
        else:
            if settings.usingAbsolute():
                p = 0 #GTP convention for abs time (=0)
            elif settings.usingNoTime():
                p = 1 #GTP convention for no time sys (>0)
                c = 0 #GTP convention for no time sys (=0)
            self.sendCommand("time_settings {0} {1} {2}".format(m, p, c))


    def beWhite(self):
        if self.gtpDebug and self.name != None:
            self._errMessage("[{0}] * now playing as White\n".format(self.name))
        self.color = self.WHITE

    def beBlack(self):
        if self.gtpDebug and self.name != None:
            self._errMessage("[{0}] * now playing as Black\n".format(self.name))
        self.color = self.BLACK

    def updateStats(self, gameRes):
        assert self.color == self.BLACK or self.color == self.WHITE, (
            "Invalid color: {0}".format(self.color))

        #update games won/totals:
        self.stats[1] += 1 #total games
        if self.color==self.WHITE:
            self.stats[3] += 1 #total as W
            if gameRes.whiteWon:
                self.stats[0] += 1 #total wins
                self.stats[2] += 1 #wins as W
        else: # BLACK
            self.stats[5] += 1 #total as B
            if not gameRes.whiteWon:
                self.stats[0] += 1 #total wins
                self.stats[4] += 1 #wins as B

        # update max time/move overall
        maxtt = self.maxTimeTaken.total_seconds()
        if maxtt > self.stats[6]: self.stats[6] = maxtt #max t/move for match

    @classmethod
    def fromCommandLine(cls, cmdLine, wkDir=None, name=None):
        windows = sys.platform.startswith('win')
        if (windows):    cmdArgs = cmdLine
        else:            cmdArgs = shlex.split(cmdLine)
        p = subprocess.Popen(cmdArgs, cwd=wkDir, bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
        return cls(process=p, name=name)

    def __init__(self, ein=None, eout=None, process=None, name=None):
        self.subProcess = process
        if process == None:
            self.ein = ein
            self.eout = eout
        else:
            self.ein = process.stdin
            self.eout = process.stdout
        self.name = name
        self.color = None
        self.quit = False
        self.stats = [0, 0, 0, 0, 0, 0, 0]
        self.maxTimeTaken = datetime.timedelta() #max time for 1 move
        self.totalTimeTaken = datetime.timedelta()
        self.movesMade=0

    def __del__(self):
        if self.subProcess != None:
            if not self.quit: self.sendCommand("quit")
            self.subProcess.wait(5)

class GameResult: #returned by playGame
    def __init__(self, whiteWon, reason, numMoves, firstTimeViolator):
        self.whiteWon = whiteWon
        self.reason = reason
        self.numMoves = numMoves
        self.ftViolator = firstTimeViolator

class TimeKeep: #stores all the extra time settings/vars used internally
    def __init__(self, timeSys, mainTime, maxTimePerMove, enforce, moveWait):
        self.timeSys = timeSys
        self.mainTime = mainTime
        self.maxTimePerMove = maxTimePerMove
        self.enforce = enforce
        self.moveWait = moveWait

class DumbarbConfig:
    def __init__(self, configFile):
        config = configparser.ConfigParser(inline_comment_prefixes='#')
        config.read(configFile)
        self.engineNames = config.sections()
        self.config = config
        assert len(self.engineNames) == 2 #DEFAULT section not counted
        #config vars in DEFAULT section
        self.numGames = int(config['DEFAULT']['numGames']) #required, no def val
        self.periodTime = int(config['DEFAULT']['periodTime']) #requried, no def val
        self.sgfDir = config['DEFAULT'].get('sgfDir', None)
        self.boardSize = int(config['DEFAULT'].get('boardSize', 19))
        self.komi = float(config['DEFAULT'].get('komi', 7.5))
        self.mainTime = int(config['DEFAULT'].get('mainTime', 0))
        self.periodCount = int(config['DEFAULT'].get('periodCount', 1))
        self.timeSys = int(config['DEFAULT'].get('timeSys', 2))
        self.initialWait = float(config['DEFAULT'].get('initialWait', 2))
        self.moveWait = float(config['DEFAULT'].get('moveWait', 0.5))
        self.enforceTime = int(config['DEFAULT'].get('enforceTime', 0)) > 0
        self.timeTolerance = float(config['DEFAULT'].get('timeTolerance', 0))

    def __getitem__(self, key):
        return self.config[key]

#returns GameResult
def playGame(whiteEngine, blackEngine, tk, sgf):
    violator=None
    consecPasses=0
    numMoves=0
    whiteEngine.beWhite()
    blackEngine.beBlack()

    # clear engine boards & stats
    for engine in (whiteEngine, blackEngine):
        engine.clear()
        engine.maxTimeTaken = datetime.timedelta() #max time for 1 move
        engine.totalTimeTaken = datetime.timedelta()
        engine.movesMade=0

    mover=blackEngine #mover moves; start with black (GTP genmove)
    placer=whiteEngine #placer just places move generated by mover (GTP play)

    while True:
        if tk.moveWait > 0: time.sleep(tk.moveWait)
        beforeMove = datetime.datetime.utcnow()
        move = mover.move()
        delta = datetime.datetime.utcnow() - beforeMove
        mover.movesMade += 1 #increments on resign/timeout, unlike numMoves
        mover.totalTimeTaken += delta
        # TODO handle time systems properly
        if delta > mover.maxTimeTaken:
            mover.maxTimeTaken = delta
            if delta.total_seconds() > tk.maxTimePerMove:
                if violator == None:
                    violator = mover.name #store first engine to violate time
                if tk.enforceTime:
                    return GameResult((mover == blackEngine), R_TIME, numMoves, violator)
        if move.lower() == 'pass':
            consecPasses += 1
        else:
            consecPasses = 0
        assert consecPasses < 2, "Engines started passing consecutively."
        if move.lower() == 'resign':
            return GameResult((mover == blackEngine), R_RESIGN, numMoves, violator)
        if sgf != None: sgf.addMove(move)
        numMoves+=1
        placer.placeOpponentStone(move)
        mover, placer = placer, mover

def printErr(message, end='\n', flush=True):
    sys.stderr.write(message + end)
    if flush: sys.stderr.flush()

def printOut(message, end='\n', flush=True):
    sys.stdout.write(message + end)
    if flush: sys.stdout.flush()

def playMatch(engine1, engine2, numGames, settings, tk, sgfDir):
    maxDgts=len(str(numGames)) #max # of digits for spacing of the game counter
    nWidth=max(len(engine1.name), len(engine2.name)) #width of name fields

    printErr("Playing games: ", end='')

    #board settings
    for engine in (engine1, engine2):
        engine.gameSetup(settings)

    white, black = engine1, engine2
    for i in range(numGames):
        #print pre-result string
        printOut(FMT_PRERESULT.format(seqno = i + 1, swidth = maxDgts, nwidth = nWidth,
                    white = white.name, black = black.name), end='')

        #SGF prepare
        if sgfDir != None:
            sgf = SGF(settings, white.name, black.name,
                        "game {0}".format(i + 1), "dumbarb {0}-game match".format(numGames))
        else:
            sgf = None

        #play the game
        gameRes = playGame(white, black, tk, sgf)

        #get/caluclate engine time stats
        engStats = []
        for engine in (engine1, engine2):
            if engine.movesMade > 0:
                avgtt = engine.totalTimeTaken.total_seconds() / engine.movesMade
            else:
                avgtt = 0
            engStats.append({'name': engine.name,
                            'maxtt': engine.maxTimeTaken.total_seconds(),
                            'tottt': engine.totalTimeTaken.total_seconds(),
                            'avgtt': avgtt})

        #print result, time stats, move count, first time violator
        if gameRes.whiteWon:
            printOut(FMT_WIN_W.format(name = white.name, nwidth = nWidth), end='', flush=False)
        else:
            printOut(FMT_WIN_B.format(name = black.name, nwidth = nWidth), end='', flush=False)
        printOut(FMT_REST.format(
                    name1 = engStats[0]['name'],
                    maxtt1 = engStats[0]['maxtt'],
                    tottt1 = engStats[0]['tottt'],
                    avgtt1 = engStats[0]['avgtt'],
                    name2 = engStats[1]['name'],
                    maxtt2 = engStats[1]['maxtt'],
                    tottt2 = engStats[1]['tottt'],
                    avgtt2 = engStats[1]['avgtt'],
                    moves = gameRes.numMoves,
                    reason = gameRes.reason,
                    vio = gameRes.ftViolator,
                    nwidth = nWidth))
        printErr(".", end = '')

        #SGF write to file
        if sgfDir != None:
            sgf.setResult(gameRes.whiteWon, gameRes.reason)
            sgf.writeToFile(sgfDir)

        #update overall stats
        for engine in (white, black):
            engine.updateStats(gameRes)

        #swap colors
        white, black = black, white

#read config
cnf = DumbarbConfig(sys.argv[1])

#calculate max time per move (exceeding gets logged or loses the game, if enforceTime=1)
if cnf.timeTolerance >= 0:
    assert cnf.periodCount == 1 or cnf.timeSys == 0 or cnf.timeSys == 1, (
                "periodCount needs to be 1 for Canadian/Japanese byoyomi when time checking."
                "Set timeTolerance to -1 to disable time checking and use this setting.")
    maxTimePerMove = cnf.periodTime + cnf.timeTolerance
else: #negative tolerance turns checking off
    maxTimePerMove = 360000 #100 hours

tk = TimeKeep(cnf.timeSys, cnf.mainTime, maxTimePerMove, cnf.enforceTime, cnf.moveWait)

#set up game settings & engines
settings = GameSettings(boardSize=cnf.boardSize, komi=cnf.komi, mainTime=cnf.mainTime,
            periodTime=cnf.periodTime, periodCount=cnf.periodCount, timeSys=cnf.timeSys)
engList = []
for engName in cnf.engineNames:
    assert len(engName.split()) == 1, "Engine name should not contain whitespace"
    e = GTPEngine.fromCommandLine(cnf[engName]['cmd'], cnf[engName].get('wkDir', None), engName)
    engList.append(e)

#mkdir for SGF files
if cnf.sgfDir != None:
    os.mkdir(cnf.sgfDir) #fail if exists: don't want to overwrite

#run the actual match
assert len(engList) == 2
time.sleep(cnf.initialWait)
playMatch(engList[0], engList[1], cnf.numGames, settings, tk, cnf.sgfDir)

#diagnostics to stderr
printErr("\nMatch ended. Overall stats:")
printErr("won games, total games, won as W, ttl as W, won as B, ttl as B, max time/move")
for eng in engList:
    printErr("{0}: {1}".format(eng.name, eng.stats))
