# dumbarb, the dumb GTP arbiter
dumbarb communicates with two [go](https://en.wikipedia.org/wiki/Go_(game)) engines using pipes and [GTP](https://www.lysator.liu.se/~gunnar/gtp/), running an n-game match between them.  It logs results with some additional data, optionally saving the games as SGF and enforcing time controls (engines losing by time or just having their misbehavior logged).

For each game, dumbarb logs the colors, result, time violations, total, maximum, and average thinking times. It can optionally enforce time controls (losing by time) in addition to logging violations. dumbarb can use one of the engines (or a third engine process) to score any games not ending in resign/timeout. SGF files are created in a directory specified in the [config file](https://github.com/StanTraykov/dumbarb/blob/master/config-example.txt).

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, use like this (terminal/command prompt):
```
> python dumbarb.py config.txt > games.log
```
## Analysing the data
Analysing results is easy if you redirect stdout to a file.  Each game will appear as one line, like this (precision of numbers reduced for brevity):

```
[001] E1 W E2 B = E2 B+Resign 177  89  89   36.319  0.408  0.428   37.925  0.4087  0.464 VIO: None
```

The fields are, in order:
1. ``[#]`` — seq no of game
2. ``<engine1>`` — name of the first engine (in config file order)
3. ``W|B`` — color of first engine
4. ``<engine2>`` — name of the second engine (in config file order)
5. ``W|B`` — color of the second engine
6. ``=`` — symbol to make output easier to read/grep
7. ``(<engine1>|<engine2>|Jigo|None)`` — name of winning engine or 'Jigo' or 'None' (result is ``None`` when no scorer is defined in config)
8. ``W/B+Resign|W/B+Time|W/B+<score>|==|XX`` — reason/score for the win or ``==`` for jigo or ``XX`` for result ``None``
9. ``<#moves(total)>`` — number of moves in the game (excluding resign, including passes)
10. ``<#moves(E1)>`` — number of moves made by E1 (including resign, if any)
11. ``<#moves(E2)>`` — number of moves made by E2 (including resign, if any)
12. ``<total thinking time(E1)>`` — total thinking time for the first engine
13. ``<average thinking time(E1)>`` — average thinking time per move for the first engine
14. ``<max thinking time(E1)>`` — maximum thinkin time for 1 move for the first engine
15. ``<total thinking time(E2)>`` — total thinking time for the second engine
16. ``<average thinking time(E2)>`` — average thinking time per move for the second engine
17. ``<max thinking time(E2)>`` — maximum thinkin time for 1 move for the second engine
18. ``VIO:`` — symbol to make output easier to read/grep
19. ``<violations>`` — list of violations in the format ``<engine> <moveNum>[<time taken>], ...`` or ``None``

You can then search and count``(grep "..." games.log | wc -l)``, for example:

* ``"= engine"`` — total games engine won
* ``"engine W"`` — total games (won or lost) as white
* ``"engine W+"`` — total games won as white

You can check average thinking time for the whole match by summing all total thinking times and dividing by all the moves by the engine:
```
> gawk '{mv1 +=$10; mv2 +=$11; tt1+=$12; tt2+=$15}; END {print tt1/mv1; print tt2/mv2}' games.log
```

Or you can sort by a field or two (see above for numbers), for example, to see top10 max thinking times
```
> sort -gk14 games.log | tail -n10 && echo && sort -gk17 games.log | tail -n10
```
## Config file
Take a look a the [example config file](https://github.com/StanTraykov/dumbarb/blob/master/config-example.txt).
