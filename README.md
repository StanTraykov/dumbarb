# dumbarb, the dumb GTP arbiter
dumbarb communicates with two [go](https://en.wikipedia.org/wiki/Go_(game)) engines using pipes and [GTP](https://www.lysator.liu.se/~gunnar/gtp/), running an n-game match between them.  It sets up the board and time system, and logs results with some additional data, optionally saving the games as SGF and enforcing time controls (engines losing by time instead of just having their misbehavior logged).

dumbarb lives up to its name when it comes to go: it relies on one of the engines eventually sending a 'resign' through GTP. Engines should be set up accordingly. If both engines start passing consecutively, dumbarb will exit. dumbarb can enforce time controls with a specified tolerance or just log the maximum time taken per move for each game and engine. SGF files are created in a separate directory that must not exist before launching, see the Config file section for all settings.

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, use like this (e.g. in a terminal/Windows command prompt):
```
> python dumbarb.py config.txt > games.log
```
## Analysing the data
Analysing results is easy if you redirect stdout to a file.  Each game will appear as one line:
```
[game#] engine WHITE vs other_engine BLACK = winner WIN color ; MAXTIME: engine1 seconds1 engine2 seconds2 ; MV: #moves +Reason
```

where:
* ``game#`` — seq no of game
* ``engine``, ``other_engine`` — names of the engines (white is always left)
* ``winner`` — name of the winning engine
* ``color`` — color of the winning engine (WHITE if engine, BLACK otherwise)
* ``seconds1`` — max time taken for 1 move by engine1 (microsecond precision)
* ``seconds2`` — max time taken for 1 move by engine2
* ``engine1``, ``engine2`` — names of the same engines, but in config file order
* ``#moves`` — number of moves (excluding the 'resign' move)
* reason — how the game ended 'resign' or 'time' (only if enforcing time controls)

example:
```
[1] e1 WHITE vs e2 BLACK = e1 WIN WHITE ; MAXTIME: e1 3.983123 e2 4.016786 ; MV: 327 +Resign
```
you can then search, e.g. ``(grep "..." games.log | wc -l)`` for:

* ``"engine WIN"`` — total games engine won
* ``"engine WHITE"`` — total games (won or lost) as white
* ``"engine WIN WHITE"`` — total games won as white, etc., etc.

check whether engines behaved within time tolerances:
```
> sort -gk14 games.log | tail -n7 && echo && sort -gk16 games.log | tail -n7
```
check average max time per move:
```
> gawk '{i++; sum1 +=$14; sum2 +=$16 }; END {print sum1/i; print sum2/i}' games.log
```
## Config file
The config file has three sections, the first named ``DEFAULT``, the other two as you like (but no whitespace). The section names will be the "engine names". The ``DEFAULT`` section should include parameters ``numGames`` (total number of games to play) and ``periodTime`` (effectively seconds per move in the usual cases). The engine sections should have ``cmd``, specifying the command line for the engine, and (opitonally) ``wkDir``, the working directory. See example config file below:
```
[DEFAULT]

   # ----- required ------

   numGames=4     # total number of games to play
   periodTime=5   # seconds per period (= seconds per move, usually)

   # ----- optional ----- (you can remove / comment these out)

   #sgfDir=sgfX   # directory to create SGF files in (default: don't create)
                  # dumbarb will create the dir and fail if it already exists

   boardSize=19   # board size (default 19)
   komi=7.5       # komi (default 7.5)
   mainTime=0     # main time (default 0)

   periodCount=1  # number of stones for Canadian or
                  # number periods for Japanese byo yomi (default 1)

   timeSys=2      # time system (default 2)
                  # 0 = none; 1 = abs. time; 2 = Canadian; 3 = byo yomi 
                  # 3 (Japanese byo yomi) requires engine support (GTP command
                  # kgs-time_settings) but is the same as 2 for
                  # periodCount = 1, so 2 is the default.

   timeTolerance=-1 # If above or equal to 0, enables the enforcing of time
                  # controls (losing by time) with the specified time
                  # tolerance (microsecond precision). If an engine exceeds
                  # time by more than timeTolerance, it loses by time. Setting
                  # this to -1 disables enforcing (you can still check whether
                  # the engine behaved in the logs, see MAXTIME field).                                    
                  # Default is -1 (disabled).
                  # Suggested values: 0.050000 ( 50ms).
                  #                   0.500000 (500ms).
                  # Keep in mind you may need to change the default time
                  # buffer value in the engine.
                  
   initialWait=0  # wait this number of seconds after starting engines
                  # (default 0). Useful with timeTolerance to give engines
                  # some time to start up.

[LZ-2thr]
   # Command line for the engine (paths relative towkDir param)
   cmd=C:\Users\Stan\Downloads\leela-zero-0.12-win64\leelaz -t2 --noponder --timemanage on -g -q -b 0 -w 1ccb.txt

   # Optional working directory (default: current working directory).
   # Files in this directory will be available in relative paths for
   # command-line options and hard-coded config files (e.g. aq_config.txt
   # or leelaz_opencl_tuning). The executable itself may still need a path
   # prefix in the cmd parameter. This depends on platform.
   wkDir=C:\Users\Stan\Downloads\leela-zero-0.12-win64

[LZ-8thr]
   cmd=C:\\Users\Stan\Downloads\leela-zero-0.12-win64\leelaz -t8 --noponder --timemanage on -g -q -b 0 -w 1ccb.txt
   wkDir=C:\Users\Stan\Downloads\leela-zero-0.12-win64
```
