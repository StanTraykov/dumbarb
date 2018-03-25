#!/usr/bin/env python3
#            dumbarb, the dumb GTP arbitrator, version 0.1
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

# USAGE: python3 dumbarb.py config.txt > games.log

# DESCRIPTION:
# dumbarb communicates with two go engines using pipes/GTP, running an n-game
# match between them.  It sets up the board and time system, and logs results
# and some additional data.
#
# dumbarb is very dumb:  it relies on one of the engines eventually sending a
# 'resign' through GTP. If it hangs, that didn't happen.
#
# Analysing results is easy if you redirect stdout to a file.  Each game will
# appear as one line:
#
#   [game#] engine WHITE vs other_engine BLACK = winner WIN color ;
#				MAXTIME: engine1 seconds1 engine2 seconds2 ; MV: #moves
# where
#     game# - seq no of game
#     engine, other_engine - names of the engines (white is always left)
#     winner - name of the winning engine
#     color - color of the winning engine (WHITE if engine, BLACK otherwise)
#     seconds1 - max time taken for 1 move by engine1 (microsecond precision)
#     seconds2 - max time taken for 1 move by engine2
#     engine1, engine2 - names of the same engines, but in config file order
#     #moves - number of moves (excluding the 'resign' move)
#
# example
#     [1] e1 WHITE vs e2 BLACK = e1 WIN WHITE ; MAXTIME: e1 3.983 e2 4.016786
#				; MV: 327
#
# you can then search, e.g. (grep "..." games.log | wc -l) for:
#     "engine WIN" - total games engine won
#     "engine WHITE" - total games (won or lost) as white
#     "engine WIN WHITE" - total games won as white, etc., etc.
# also:
# > sort -k14 games.log | tail -n7 && echo && sort -k16 games.log | tail -n7
# can be used to check if the engines behaved within time tolerance

# CONFIG FILE FORMAT:
'''
# config file with three sections:
# general setup
[DEFAULT]
numGames=100
secsPerMove=5

# first engine section (no whitespace in engine names)
[testprogr]
# wkDir is optional
wkDir=C:\path\to\test ;optional
cmd=C:\path\to\test\test.exe -a -b --conf file-in-wkDir

# second engine section
[myprogram]
wkDir=C:\path\to\mypr ;optional
cmd=C:\path\to\mypr\myprogram --gtp
'''

import configparser, datetime, shlex, subprocess, sys

class GoBoard:
	def isUsingNoTime(self):	return self.timeSys == 0
	def isUsingAbsolute(self):	return self.timeSys == 1
	def isUsingCanadian(self):	return self.timeSys == 2
	def isUsingByoyomi(self):	return self.timeSys == 3
	def __init__(self, boardSize=19, mainTime=0, komi=7.5, periodTime=5, periodCount=1, timeSys=3):
		self.boardSize = boardSize
		self.mainTime = mainTime
		self.komi = komi
		self.periodTime = periodTime
		self.periodCount = periodCount
		self.timeSys = timeSys

class GTPEngine:
	BLACK='B'
	WHITE='W'
	gtpDebug=False
	quit=False

	def _errMessage(self, message):
		if self.gtpDebug:
			sys.stderr.write(message)
			sys.stderr.flush()

	def _rawRecvResponse(self):
		response = b''
		while True:
			line = self.eout.readline()
			if response != b'' and (line == b'\n' or line == b'\r\n'):
				break # break if empty line encountered (unless it is first thing)
			response += line
			if self.name != None:
				self._errMessage("[{0}] ".format(self.name))
			self._errMessage("Received: " + response.decode().rstrip() + '\n')
		return response.decode().rstrip()

	def _rawSendCommand(self, command):
		if self.name != None:
			self._errMessage("[{0}] ".format(self.name))
		self._errMessage("Sending: " + command + '\n')
		self.ein.write(command.encode() + b'\n')
		if command.lower().strip() == 'quit':
			self.quit=True

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
		if self.color == self.BLACK:	oppColor = self.WHITE
		else:							oppColor = self.BLACK
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
		self.sendCommand("boardsize " + str(goBoard.boardSize))
		self.sendCommand("komi " + str(goBoard.komi))

	def beWhite(self):
		if self.name != None: self._errMessage("[{0}] * now playing as White\n".format(self.name))
		self.color = self.WHITE

	def beBlack(self):
		if self.name != None: self._errMessage("[{0}] * now playing as Black\n".format(self.name))
		self.color = self.BLACK

	@classmethod
	def fromCommandLine(cls, cmdLine, wkDir=None, name=None):
		windows = sys.platform.startswith('win')
		if (windows):	cmdArgs = cmdLine
		else:			cmdArgs = shlex.split(cmdLine)
		p = subprocess.Popen(cmdArgs, cwd=wkDir, bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		return cls(process=p, name=name)

	def __init__(self, ein=None, eout=None, process=None, name=None):
		self.name = name
		self.color = None
		self.subProcess = process
		if process == None:
			self.ein = ein
			self.eout = eout
		else:
			self.ein = process.stdin
			self.eout = process.stdout
	
	def __del__(self):
		if self.subProcess != None:
			if not self.quit: self._rawSendCommand("quit")
			self.subProcess.wait(3)

def playGame(whiteEngine, blackEngine): # returns (whiteWon, numMoves) whiteWon=true if whiteEngine won
	numMoves=0
	whiteEngine.clear()
	whiteEngine.beWhite()
	blackEngine.clear()
	blackEngine.beBlack()
	whiteEngine.maxTimeTaken = datetime.timedelta() #max time for 1 move
	blackEngine.maxTimeTaken = datetime.timedelta()

	mover=blackEngine #mover moves, start with black (GTP genmove)
	placer=whiteEngine #placer just places move generated by mover (GTP play)

	while True:
		beforeMove = datetime.datetime.utcnow()
		move = mover.move()
		delta = datetime.datetime.utcnow() - beforeMove
		if delta > mover.maxTimeTaken: mover.maxTimeTaken = delta
		if move == 'resign': return ((mover == blackEngine), numMoves) # ret True if W won
		numMoves+=1
		placer.placeOpponentStone(move)
		mover, placer = placer, mover

def playMatch(engine1, engine2, numGames):
	#stats: won games, total gms, won as W, ttl as W, won as B, ttl as B, max time/1mv for whole match
	maxDgts=len(str(numGames))
	engine1.stats = [0, 0, 0, 0, 0, 0, 0]
	engine2.stats = [0, 0, 0, 0, 0, 0, 0]
	white = engine1
	black = engine2

	for i in range(numGames):
		#write pre-result string to stdout
		sys.stdout.write("[{0:0{1}}] {2} WHITE vs {3} BLACK = ".format(i + 1, maxDgts, white.name, black.name))
		sys.stdout.flush()

		#play the game
		(whiteWon, numMoves) = playGame(white, black)
		maxtt1=engine1.maxTimeTaken.total_seconds() #preserves microseconds in fractional part
		maxtt2=engine2.maxTimeTaken.total_seconds()

		#write result, max time taken per 1 move for both players
		if whiteWon:
			sys.stdout.write("{0} WIN WHITE ; ".format(white.name))
		else:
			sys.stdout.write("{0} WIN BLACK ; ".format(black.name))
		sys.stdout.write("MAXTIME: {0} {1:9} {2} {3:9} ; MV: {4:3}\n".format(engine1.name, maxtt1, engine2.name, maxtt2, numMoves))
		sys.stdout.flush()

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
		if maxtt1 > engine1.stats[6]: engine1.stats[6]=maxtt1 #max time taken per 1 move for whole match
		if maxtt2 > engine2.stats[6]: engine2.stats[6]=maxtt2 #max time taken per 1 move for whole match

		#swap colors
		white, black = black, white

#read config & set up engines
config = configparser.ConfigParser()
config.read(sys.argv[1])
sections = config.sections()
assert len(sections) == 2 #excluding DEFAULT
numGames = int(config['DEFAULT']['numGames'])
secsPerMove = int(config['DEFAULT']['secsPerMove'])
board = GoBoard(periodTime=secsPerMove)
engList = []
for engineName in sections:
	assert len(engineName.split()) == 1, "Engine name should not contain whitespace"
	e = GTPEngine.fromCommandLine(config[engineName]['cmd'], config[engineName].get('wkDir', None), engineName)
	e.gameSetup(board)
	engList.append(e)

#run the actual match
assert len(engList) == 2
playMatch(engList[0], engList[1], numGames)

#diagnostics to stderr
sys.stderr.write("Match ended. Overall stats:\n")
sys.stderr.write("won games, total games, won as W, ttl as W, won as B, ttl as B, max time/move\n")
for eng in engList:
	sys.stderr.write("{0}: {1}\n".format(eng.name, eng.stats))