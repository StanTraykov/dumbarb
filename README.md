# dumbarb, the dumb GTP arbiter
dumbarb communicates with two [go](https://en.wikipedia.org/wiki/Go_(game)) engines using pipes and [GTP](https://www.lysator.liu.se/~gunnar/gtp/), running an n-game match between them.  It sets up the board and time system, and logs results and some additional data.

dumbarb is very dumb: it relies on one of the engines eventually sending a 'resign' through GTP. If it hangs, that didn't happen.

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, use like this (e.g. in a terminal/Windows command prompt):
```
> python dumbarb.py config.txt > games.log
```
## Config file
The config file has three sections, the first named ``DEFAULT``, the other two as you like (but no whitespace). The section names will be the "engine names". The ``DEFAULT`` section should include parameters ``numGames`` (total number of games to play) and ``secsPerMove`` (seconds per move). The engine sections should have ``cmd``, specifying the command line for the engine, and (opitonally) ``wkDir``, the working directory. See example config file below:
```
[DEFAULT]
numGames=400
secsPerMove=5

[LZT02]
wkDir=C:\Users\Stan\Downloads\leela-zero-0.12-win64
cmd=C:\Users\Stan\Downloads\leela-zero-0.12-win64\leelaz -t2 --noponder --timemanage on -g -b 5 -q -w 1ccb.txt

[LZT08]
wkDir=C:\Users\Stan\Downloads\leela-zero-0.12-win64
cmd=C:\Users\Stan\Downloads\leela-zero-0.12-win64\leelaz -t8 --noponder --timemanage on -g -b 5 -q -w 1ccb.txt
```
## Analysing the data
Analysing results is easy if you redirect stdout to a file.  Each game will appear as one line:
```
[game#] engine WHITE vs other_engine BLACK = winner WIN color ; MAXTIME: engine1 seconds1 engine2 seconds2 ; MV: #moves
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

example:
```
[1] e1 WHITE vs e2 BLACK = e1 WIN WHITE ; MAXTIME: e1 3.983123 e2 4.016786 ; MV: 327
```
you can then search, e.g. ``(grep "..." games.log | wc -l)`` for:

* ``"engine WIN"`` — total games engine won
* ``"engine WHITE"`` — total games (won or lost) as white
* ``"engine WIN WHITE"`` — total games won as white, etc., etc.

check whether engines behaved within time tolerances:
```
> sort -gk14 games.log | tail -n7 && echo && sort -gk16 games.log | tail -n7
```
check average time per move:
```
> gawk '{i++; sum1 +=$14; sum2 +=$16 }; END {print sum1/i; print sum2/i}' games.log
```
