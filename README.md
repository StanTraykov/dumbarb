# dumbarb, the dumb GTP arbiter
dumbarb communicates with two [go](https://en.wikipedia.org/wiki/Go_(game)) engines using pipes and [GTP](https://www.lysator.liu.se/~gunnar/gtp/), running an n-game match between them.  It sets up the board and time system, and logs results with some additional data, optionally saving the games as SGF and enforcing time controls (engines losing by time instead of just having their misbehavior logged).

dumbarb lives up to its name when it comes to go: it relies on one of the engines eventually sending a 'resign' through GTP. Engines should be set up accordingly. If both engines start passing consecutively, dumbarb will exit. dumbarb can optionally enforce time controls with a specified tolerance and always logs the first time violator and the maximum and average time taken per move for each game and engine. SGF files are created in a separate directory that must not exist before launching. See the Config file section for all settings.

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, use like this (e.g. in a terminal/Windows command prompt):
```
> python dumbarb.py config.txt > games.log
```
## Analysing the data
Analysing results is easy if you redirect stdout to a file.  Each game will appear as one line:
```
[#] engW WHITE vs engB BLACK = winner WIN color ; TM: eng1 sMax1 sAvg1 eng2 sMax2 sAvg2 ; MV: mvs +reason ; VIO: vio
```

where:
* ``#`` — seq no of game
* ``engW``, ``engB`` — names of the engines (white is always left)
* ``winner`` — name of the winning engine
* ``color`` — color of the winning engine (WHITE if engW, BLACK if engB)
* ``eng1``, ``eng2`` — names of the same engines, but in config file order (not white, black)
* ``sMax1``, ``sMax2`` — max time taken for 1 move by eng1 & 2 (seconds with microsecond precision)
* ``sAvg1``, ``sAvg2`` — average time taken for 1 move by eng1 & 2 (seconds with microsecond precision)
* ``mvs`` — number of moves (excluding the 'resign' move)
* ``reason`` — how the game ended 'resign' or 'time' (only if enforcing time controls)
* ``vio`` — the name of the engine that first violated time (or ``None`` if none did)

example (with reduced precision for brevity):
```
[1] e2 WHITE vs e1 BLACK = e2 WIN WHITE ; TM: e1 3.92 3.12 e2 4.20 3.01 ; MV: 327 +Resign ; VIO: None
```
you can then search, e.g. ``(grep "..." games.log | wc -l)`` for:

* ``"engine WIN"`` — total games engine won
* ``"engine WHITE"`` — total games (won or lost) as white
* ``"engine WIN WHITE"`` — total games won as white, etc., etc.

check whether engines behaved within time tolerances:
```
> sort -gk14 games.log | tail -n7 && echo && sort -gk17 games.log | tail -n7
```
check average max time per move:
```
> gawk '{i++; sum1 +=$14; sum2 +=$17 }; END {print sum1/i; print sum2/i}' games.log
```
## Config file
Take a look a the [example config file](https://github.com/StanTraykov/dumbarb/blob/master/config-example.txt).
