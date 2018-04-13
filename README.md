# dumbarb, the semi-smart GTP arbiter

dumbarb is a GTP arbiter, a program that plays matches between computer [go](https://en.wikipedia.org/wiki/Go_(game)) programs that support the [GTP](https://www.lysator.liu.se/~gunnar/gtp/) protocol (version 2).

Like most arbiters, dumbarb logs results and outputs SGFs. Its distinguishing features are
* time-controlled games with very exact timekeeping, checking, and logging (down to microsecond precision)
* managed engine processes: dumbarb is multi-threaded to avoid unresponsiveness, keeps track of engines, restarts them if they hang
* flexible config files
* engine stderr logging to individual files for each game

## Usage
dumbarb is written in Python 3. Assuming it is available as ``python``, run it like this:

```
> python dumbarb.py [<switches>] <config file> [<config file 2> ...]
```

Config files contain engine definitions and settings for one or more matches which dumbarb will try to arrange. You can split up the config into multiple files (e.g. one for engine definitions, one for matches). Here is an [example config file](https://github.com/StanTraykov/dumbarb/blob/master/config-example.txt).

## Output

dumbarb automatically creates a directory for each match (based on the names of the engines and the match label, if any). In it, it stores a ``.log`` file with game results and other stats. SGF files and stderr logs are put in subdirectories.

### Format
Each game will appear as one line in the log file, with whitespace-delimited fields in the follwing order:

The fields are, in order:
1. ``YYMMDD-HH:MM:SS`` timestamp
2. ``[#<num>]`` — seq no of game
3. ``<eng 1>`` — name of the first engine
4. ``W|B`` — color of first engine
5. ``<eng 2>`` — name of the second engine (in config file order)
6. ``W|B`` — color of the second engine
7. ``=`` — just a symbol
8. ``(<eng 1>|<eng 2>|Jigo|None|UFIN|ERR)`` — name of winning engine or ``Jigo``, ``None`` (ended with passes but couldn't score), ``UFIN`` (unfinished), or ``ERR`` (some error occured).
9. ``(W|B)+Resign|(W|B)+Time|(W|B)+<score>|==|XX|SD|EE|IL`` — color and score or reason for the win, or:
    * ``==`` — Jigo
    * ``XX`` — no scoring requested
    * ``SD`` — problem with scorer engine
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

### Grep
You can then search and count ``(grep "..." games.log | wc -l)``, for example:

* ``"engine W"`` — total games played by engine as white
* ``"engine W+"`` — total games engine won as white
* ``"engine .+"`` — total games engine won as either color

### Gawking

You can, for example, check average thinking time for the whole match by summing all total thinking times and dividing by all the moves by the engine (see above for field numbers):
```
gawk '{mv1+=$10; mv2+=$11; tt1+=$12; tt2+=$15} END{print tt1/mv1; print tt2/mv2}' games.log
```

Or, to get a reasonable summary of the whole match (this script is included as ``summarize.sh``):
```
gawk '{
    tmv+=$9; mvmax=($9>mvmax?$9:mvmax);mvmin=($9<mvmin||mvmin==0?$9:mvmin)

    ++t; p1=$2; p2=$4; if($3=="W")p1W++; if($5=="W")p2W++; if($3=="B")p1B++; if($5=="W")p2B++;
    if($7==p1)p1wins++; if($7==p1&&$3=="W")p1winsW++; if($7==p1&&$3=="B")p1winsB++;
    if($7==p2)p2wins++; if($7==p2&&$5=="W")p2winsW++; if($7==p2&&$5=="B")p2winsB++;

    p1mv+=$10; p2mv+=$11; p1tt+=$12; p2tt+=$15;
    p1mtm=($14>p1mtm?$14:p1mtm); p2mtm=($17>p2mtm?$17:p2mtm);
    }
    END{
        printf "%d total games, %d total moves,  %.2f avg moves/game, %d min, %d max\n",
            t, tmv, tmv/t, mvmin, mvmax;

        printf "%s: %d wins, %d wins from %d total as W, %d wins from %d total as B\n",
            p1, p1wins, p1winsW, p1W, p1winsB, p1B;
        printf "%s: %d wins, %d wins from %d total as W, %d wins from %d total as B\n",
            p2, p2wins, p2winsW, p2W, p2winsB, p2B;

        printf "%s: %f total thinking time, %f avg/move, %f max\n",
            p1, p1tt, p1tt/p1mv, p1mtm;
        printf "%s: %f total thinking time, %f avg/move, %f max\n",
            p2, p2tt, p2tt/p2mv, p2mtm;

    }' games.log
```

### Sorting
Or you can sort by a field or two (see above for numbers), for example, to see top10 max thinking times:
```
sort -gk14 games.log | tail -n10 && echo && sort -gk17 games.log | tail -n10
```

### Checking for duplicate games
To find out if the engines repeated the same game during a match or several matches, you could run something like this from the SGF dir (also checks subdirs). NOTE that this relies on dumbarb's way of saving SGF files (with only the first line containing variable info such as player names, dates, etc.). It would not work with SGF files in general.
```
find . -type f -iname "*.sgf" -exec sh -c "echo -n '{} ' >> chksums; grep -v dumbarb {} | md5sum >> chksums" \;
sort -k2 chksums | uniq -Df 1
```
