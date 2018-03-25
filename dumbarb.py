#!/usr/bin/env python3
#               dumbarb, the dumb GTP arbiter, version 0.1
#      Copyright (C) 2017 Stanislav Traykov st-at-gmuf-com / GNU GPL

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
DUMBVER = "0.1.2"

R_RESIGN = "Resign" # } don't change: used in SGF output
R_TIME = "Time"     # }

class SGF:
    SGF_AP_VER = DUMBARB + ':' + DUMBVER
    SGF_BEGIN = "(;GM[1]FF[4]CA[UTF-8]AP[{0}]RU[{1}]SZ[{2}]KM[{3}]GN[{4}]PW[{5}]PB[{6}]DT[{7}]EV[{8}]RE[{9}]\n"
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
                            self.board.size, #2 SZ
                            self.board.komi, #3 KM
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
            assert len(coord) <= 3, "SGF.addMove got something other than pass/coords: {0}".format(coord)            
            idxLtoR = string.ascii_lowercase.index(coord[0].lower())
            if idxLtoR > 8: idxLtoR -= 1 #GTP skips i, SGF doesn't, so reduce by 1 from j onwards
            idxTtoB = abs(int(coord[1:])-self.board.size)
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

    def __init__(self, board, whiteName, blackName, gameName, eventName):
        self.datesIso = datetime.datetime.now().date().isoformat()
        self.result = None
        self.blacksTurn = True
        self.movesString = ""
        self.board = board
        self.whiteName = whiteName
        self.blackName = blackName
        self.gameName = gameName
        self.eventName = eventName

class GoBoard:
    def isUsingNoTime(self):   return self.timeSys == 0
    def isUsingAbsolute(self): return self.timeSys == 1
    def isUsingCanadian(self): return self.timeSys == 2
    def isUsingByoyomi(self):  return self.timeSys == 3
    def __init__(self, size=19, komi=7.5, mainTime=0, periodTime=5, periodCount=1, timeSys=2):
        self.size = size
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
        assert self.color == self.BLACK or self.color == self.WHITE, "Invalid color: {0}".format(self.color)
        return self.getResponseFor("genmove " + self.color)

    def placeOpponentStone(self, coord): #place an opponent's stone on the board (GTP play)
        assert self.color == self.BLACK or self.color == self.WHITE, "Invalid color: {0}".format(self.color)
        if self.color == self.BLACK:    oppColor = self.WHITE
        else:                           oppColor = self.BLACK
        return self.sendCommand("play {0} {1}".format(oppColor, coord))

    def clear(self): #clear the board
        self.sendCommand("clear_board")

    def gameSetup(self, goBoard):
        m = goBoard.mainTime
        p = goBoard.periodTime
        c = goBoard.periodCount

        if goBoard.isUsingByoyomi():
            self.sendCommand("kgs-time_settings byoyomi {0} {1} {2}".format(m, p, c))
        else:
            if goBoard.isUsingAbsolute():
                p = 0 #GTP convention for abs time (=0)
            elif goBoard.isUsingNoTime():
                p = 1 #GTP convention for no time sys (>0)
                c = 0 #GTP convention for no time sys (=0)
            self.sendCommand("time_settings {0} {1} {2}".format(m, p, c))
        self.sendCommand("boardsize " + str(goBoard.size))
        self.sendCommand("komi " + str(goBoard.komi))

    def beWhite(self):
        if self.gtpDebug and self.name != None: self._errMessage("[{0}] * now playing as White\n".format(self.name))
        self.color = self.WHITE

    def beBlack(self):
        if self.gtpDebug and self.name != None: self._errMessage("[{0}] * now playing as Black\n".format(self.name))
        self.color = self.BLACK

    @classmethod
    def fromCommandLine(cls, cmdLine, wkDir=None, name=None):
        windows = sys.platform.startswith('win')
        if (windows):    cmdArgs = cmdLine
        else:            cmdArgs = shlex.split(cmdLine)
        p = subprocess.Popen(cmdArgs, cwd=wkDir, bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return cls(process=p, name=name)

    def __init__(self, ein=None, eout=None, process=None, name=None):
        self.name = name
        self.color = None
        self.subProcess = process
        self.quit = False
        if process == None:
            self.ein = ein
            self.eout = eout
        else:
            self.ein = process.stdin
            self.eout = process.stdout

    def __del__(self):
        if self.subProcess != None:
            if not self.quit: self.sendCommand("quit")
            self.subProcess.wait(5)

def playGame(whiteEngine, blackEngine, maxTimePerMove, enforceTime=False, sgf=None): # returns (whiteWon, reason, numMoves) whiteWon=true if whiteEngine won
    violator=None
    consecPasses=0
    numMoves=0
    whiteEngine.beWhite()    
    blackEngine.beBlack()

    #for stats
    for engine in (whiteEngine, blackEngine):
        engine.clear()
        engine.maxTimeTaken = datetime.timedelta() #max time for 1 move
        engine.totalTimeTaken = datetime.timedelta()
        engine.movesMade=0

    mover=blackEngine #mover moves, start with black (GTP genmove)
    placer=whiteEngine #placer just places move generated by mover (GTP play)

    while True:
        beforeMove = datetime.datetime.utcnow()
        move = mover.move()
        delta = datetime.datetime.utcnow() - beforeMove
        mover.movesMade += 1 #increments on resign/timeout, unlike numMoves
        mover.totalTimeTaken += delta
        if delta > mover.maxTimeTaken:
            mover.maxTimeTaken = delta
            if delta.total_seconds() > maxTimePerMove:
                if violator == None:
                    violator = mover.name #first engine to violate time
                if enforceTime:
                    return ((mover == blackEngine), R_TIME, numMoves, violator)                
        if move == 'pass':
            consecPasses += 1
        else:
            consecPasses = 0
        assert consecPasses < 2, "Engines started passing consecutively."        
        if move.lower() == 'resign': return ((mover == blackEngine), R_RESIGN, numMoves, violator)
        if sgf != None: sgf.addMove(move)
        numMoves+=1
        placer.placeOpponentStone(move)
        mover, placer = placer, mover

def playMatch(engine1, engine2, numGames, board, maxTimePerMove, enforceTime, sgfDir=None):
    #stats: won games, total gms, won as W, ttl as W, won as B, ttl as B, max time/1mv for whole match
    maxDgts=len(str(numGames))
    engine1.stats = [0, 0, 0, 0, 0, 0, 0]
    engine2.stats = [0, 0, 0, 0, 0, 0, 0]
    engine1.gameSetup(board)
    engine2.gameSetup(board)
    white = engine1
    black = engine2

    sys.stderr.write("Playing games: ")
    sys.stderr.flush()

    for i in range(numGames):
        #write pre-result string to stdout
        sys.stdout.write("[{0:0{1}}] {2} WHITE vs {3} BLACK = ".format(i + 1, maxDgts, white.name, black.name))
        sys.stdout.flush()

        #SGF prepare
        if sgfDir != None:            
            sgf = SGF(board, white.name, black.name, "game {0}".format(i + 1), "dumbarb {0}-game match".format(numGames))
        else:
            sgf = None

        #play the game
        (whiteWon, reason, numMoves, violator) = playGame(white, black, maxTimePerMove, enforceTime, sgf)

        #stats
        maxtt1 = engine1.maxTimeTaken.total_seconds() #preserves microseconds in fractional part
        maxtt2 = engine2.maxTimeTaken.total_seconds()
        if engine1.movesMade > 0:
            avgtt1 = engine1.totalTimeTaken.total_seconds() / engine1.movesMade
        else:
            avgtt1 = None
        if engine2.movesMade > 0:
            avgtt2 = engine2.totalTimeTaken.total_seconds() / engine2.movesMade
        else:
            avgtt2 = None

        #write result, max time taken per 1 move for both players
        if whiteWon:
            sys.stdout.write("{0} WIN WHITE ; ".format(white.name))
        else:
            sys.stdout.write("{0} WIN BLACK ; ".format(black.name))
        sys.stdout.write("TM: {0} {1:9} {2:9} {3} {4:9} {5:9}; MV: {6:3} +{7} VIO: {8}\n".format(engine1.name, maxtt1, avgtt1, engine2.name, maxtt2, avgtt2, numMoves, reason, violator))
        sys.stdout.flush()
        sys.stderr.write(".")
        sys.stderr.flush()

        #SGF write to file
        if sgfDir != None:
            sgf.setResult(whiteWon, reason)
            sgf.writeToFile(sgfDir)

        #update stats
        white.stats[1] += 1 #total games
        black.stats[1] += 1 #total games
        white.stats[3] += 1 #total as W
        black.stats[5] += 1 #total as B
        if whiteWon:
            white.stats[2] += 1 #wins as W
            white.stats[0] += 1 #total wins
        else:
            black.stats[4] += 1 #wins as B
            black.stats[0] += 1 #total wins
        if maxtt1 > engine1.stats[6]: engine1.stats[6] = maxtt1 #max time taken per 1 move for whole match
        if maxtt2 > engine2.stats[6]: engine2.stats[6] = maxtt2 #max time taken per 1 move for whole match

        #swap colors
        white, black = black, white

#read config & set up engines
config = configparser.ConfigParser(inline_comment_prefixes='#')
config.read(sys.argv[1])
sections = config.sections()
assert len(sections) == 2 #excluding DEFAULT

numGames = int(config['DEFAULT']['numGames'])
periodTime = int(config['DEFAULT']['periodTime'])
sgfDir = config['DEFAULT'].get('sgfDir', None)
boardSize = int(config['DEFAULT'].get('boardSize', 19))
komi = float(config['DEFAULT'].get('komi', 7.5))
mainTime = int(config['DEFAULT'].get('mainTime', 0))
periodCount = int(config['DEFAULT'].get('periodCount', 1))
timeSys = int(config['DEFAULT'].get('timeSys', 2))
initialWait = int(config['DEFAULT'].get('initialWait', 2))
enforceTime = int(config['DEFAULT'].get('enforceTime', 0)) > 0

timeTolerance = float(config['DEFAULT'].get('timeTolerance', -1))
if timeTolerance >= 0:
    assert mainTime == 0, "Cannot enforce time controls with mainTime>0"
    assert timeSys == 2 and periodCount == 1 or timeSys == 3, "Cannot enforce time controls with this setup (try timeSys=2, periodCount=1)"
    maxTimePerMove = periodTime + timeTolerance
else:
    maxTimePerMove = 360000 #100 hours

board = GoBoard(size=boardSize, komi=komi, mainTime=mainTime, periodTime=periodTime, periodCount=periodCount, timeSys=timeSys)
engList = []
for engineName in sections:
    assert len(engineName.split()) == 1, "Engine name should not contain whitespace"
    e = GTPEngine.fromCommandLine(config[engineName]['cmd'], config[engineName].get('wkDir', None), engineName)
    time.sleep(initialWait)
    engList.append(e)

#mkdir for SGF files
if sgfDir != None:
    os.mkdir(sgfDir) #fail if exists: don't want to overwrite

#run the actual match
assert len(engList) == 2
playMatch(engList[0], engList[1], numGames, board, maxTimePerMove, enforceTime, sgfDir)

#diagnostics to stderr
sys.stderr.write("\nMatch ended. Overall stats:\n")
sys.stderr.write("won games, total games, won as W, ttl as W, won as B, ttl as B, max time/move\n")
for eng in engList:
    sys.stderr.write("{0}: {1}\n".format(eng.name, eng.stats))