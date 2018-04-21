# dumbarb, the semi-smart GTP arbiter

dumbarb is a GTP arbiter, a program that runs matches between computer [go](https://en.wikipedia.org/wiki/Go_(game)) programs that support the [GTP](https://www.lysator.liu.se/~gunnar/gtp/) protocol (version 2).

Like most arbiters, dumbarb logs results and can output SGFs. Its distinguishing features are
* time-controlled games with very exact timekeeping, checking, and logging (down to microsecond precision)
* managed engine processes: dumbarb is multi-threaded, keeps track of engines, tries to restart them, etc.
* flexible config files allowing multiple matches and engine definitions (with settings interpolation into the command line)
* engine stderr logging to individual files for each game

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, run it like this:

```
> python dumbarb.py [<switches>] <config file> [<config file 2> ...] [-o output-folder]
```

Config files contain engine definitions and settings for one or more matches which dumbarb will try to arrange. You can split up the config into multiple files (e.g. one for engine definitions, one for matches). Documentation for all options can be [found here](CONFIG.md). You could also use the [minimal config file](https://github.com/StanTraykov/dumbarb/blob/master/config-minimal.txt) as a start.

### Continuing interrupted runs

By default, if a match folder already exists, dumbarb will create another one (with a suffix ``-001``, ``-002``, etc.). Instead of this, dumbarb can analyze match folders and continue from where it was interrupted. Incomplete single games cannot be restored, but any game-specific log files will be saved by renaming. In this mode, only the original match folders will be examined; folders with ``-001``, etc. suffixes will be ignored. To instruct dumbarb to continue an interrupted run, use the ``-c``/``--continue`` switch. For best results, combine it with the ``-o``/``--outdir`` switch:
```
> python dumbarb.py <config file(s)> -co session-folder
```
The command above will run all matches in ``session-folder`` (which will be created, if necessary). Issuing it again will continue from an interrupted run.

## Output

dumbarb automatically creates a folder for each match (based on the names of the engines and the match label, if any). In it, it stores:
* a ``<match>.log`` file with several data fields for each game: result, time stats (max/total/average per move), time violations, etc.
* a ``<match>.mvtimes`` file with move numbers, coordinates, and times for each move in a game (one game per line)
* a ``<match>.run`` file with engine command lines, names, version numbers, restarts and other information on engine behavior
* subfolders ``SGFs`` and ``stderr`` for SGF and engine standard error logs.

### Format
Each game will appear as one line in the log file, with whitespace-delimited fields.

<details> <summary><strong>Format spec <em>(click me)</em></strong></summary>
   
The fields are, in order:

1. ``YYMMDD-HH:MM:SS`` — timestamp
2. ``[#<num>]`` — seq no of game
3. ``<eng 1>`` — name of the first engine
4. ``W|B`` — color of first engine
5. ``<eng 2>`` — name of the second engine (in config file order)
6. ``W|B`` — color of the second engine
7. ``=`` — just a symbol
8. ``<eng 1>|<eng 2>|Jigo|None|UFIN|ERR`` — name of winning engine or ``Jigo``, ``None`` (ended with passes but couldn't score), ``UFIN`` (unfinished), or ``ERR`` (some error occured).
9. ``(W|B)+Resign|(W|B)+Time|(W|B)+<score>|==|XX|SD|EE|IL`` — color and score or reason for the win, or:
    * ``==`` — Jigo | ``XX`` — no scoring requested | ``SD`` — problem with scorer engine
    * ``IL`` — one of the engines complained about an illegal move
    * ``EE`` — some error occured
10. ``<total moves>`` — number of moves in the game (excluding resign, including passes)
11. ``<eng 1 moves>`` — number of moves made by the first engine (including resign, if any)
12. ``<eng 2 moves>`` — number of moves made by the second engine (including resign, if any)
13. ``<eng 1 total thinking time>`` — total thinking time for the first engine
14. ``<eng 1 average thinking time>`` — average thinking time per move for the first engine
15. ``<eng 1 max thinking time>`` — maximum thinking time for 1 move for the first engine
16. ``<eng 2 total thinking time>`` — total thinking time for the second engine
17. ``<eng 2 average thinking time>`` — average thinking time per move for the second engine
18. ``<eng 2 max thinking time>`` — maximum thinking time for 1 move for the second engine
19. ``VIO:`` — just a symbol
20. ``<violations>`` — list of time violations in the format ``<engine> <moveNum>[<time taken>]`` or ``None`` if no violations occured

</details>

### Analyzing
The files can be analyzed with your favorite tools (perl, python, gawk, etc.), or you can use the bundled ``dumbutil.py`` to generate human-readable match summaries:

```
> python dumbutil.py -s Test1_Test2_ExampleMatch.log
                    100 games, total moves 23598, avg 236.0, min 126, max 388
         W   B  total wins   wins as W   wins as B  avg t/mv  max t/mv  viols
Test1:  50  50  38 [38.0%]  21 [42.0%]  17 [34.0%]    2.001s    4.794s  0/  0
Test2:  50  50  62 [62.0%]  33 [66.0%]  29 [58.0%]    1.947s    5.964s  1/  1
bad wins, being first to exceed time: Test1  0; Test2  0 (NOT reflected above)
total time thunk: Test1: 6:35:18; Test2: 6:24:12
```

Here ``viols`` shows the number of time control violations. The first number is first violations within a game: those that would have ended it with a loss by time, if ``enforceTime`` was set to on. The second number is total violations and includes violations in games where time controls were already violated by one or both engines. If ``encorceTime`` was on (the default), both numbers should be the same, as the games ended after the first violation (W+Time/B+Time).

The ``bad wins`` below show the number of wins that are invalid, because the winner violated time before their opponent resigned or the game was scored (and was the first player to do so). These invalid wins are NOT accounted for in the printed summary values and should be subtracted. Bad wins should always be zero if ``enforceTime`` was on.



### Checking for duplicate games
``dumbutil.py`` can check whether SGF files in a given folder (and all subfolders) contain identical moves. The argument is ``-d <path>``. For example, this command will check the current folder:

```
> python dumbutil.py -d .
```
