# dumbarb config file format

* **[Match section](#match-section)**: [Game setup](#game-setup) | [Basic params](#basic-parameters) | [Waits](#wait-intervals) | [GTP timeouts](#gtp-timeouts) | [Engine defaults](#engine-defaults) 
* **[Engine section](#engine-section)**: [Basic params](#basic-parameters-1) | [Miscellaneous](#miscellaneous) 


A dumbarb config file consists of sections that begin with a line containing the section name in square brackets and terminate at the start of another section or EOF. Each section contains parameters in the form ``name = value``, with each name-value pair starting on a new line. Multi-line parameter values are permitted when indented more than the parameter name (leading whitespace will be stripped from each line). Parameter names are case insensitive; section names are NOT.

Each sections describes either an engine or a match between two engines, except for the ``[DEFAULT]`` section, which can contain default values for all sections (both match and engine). Engine sections contain no spaces in their name, match sections contain at least one. 

The match section name will also be used as a folder name for storing match results and logs. The match name syntax is ``[Engine1 Engine2 MatchLabel]``, where ``Engine1`` and ``Engine2`` are engines (defined in their own sections) and match label is an optional label for the match. Each element of a section name may be at most 20 ASCII alphanumeric or ``+-.,()`` characters, cannot begin with ``+-.,`` and cannot end in a dot. A section can be deactivated by making its name start with ``$``.

If a parameter is omitted from the config file, dumbarb uses its internal defaults, documented below. Relying on these defaults (whenever suitable) is a good way of keeping the config file short and manageable.

It is possible to specify more than one config file when starting dumbarb, e.g. a file with match parameters and a file with engine parameters.

A very simple config file could look like this:

```
[DEFAULT]
TimeSys = 1     # Absolute time
MainTime = 900  # 15 minutes
EnforceTime = yes

# Matches

[ExampleBot DemoEngine MainTest]
NumGames = 100   # play 100 games (using default settings)

[ExampleBot DemoEngine ByoyomiTest]
NumGames = 200   # play 200 games
MainTime = 60    # 1 minute main time
PeriodCount = 5  # 5 periods x
PeriodTime = 20  # 20 seconds
TimeSys = 3      # Japanese byo yomi

# Engines

[ExampleBot]
WkDir = /path/to/engine-folder
Cmd = example --play=well --logfile={matchdir}/{name}.log

[DemoEngine]
WkDir = C:\path\to\engine-folder
Cmd = demoeng /extra-strong /log {matchdir}\{name}.log

```

## Match section
### Game setup
#### ``TimeSys``
The time system to be used (default 2). Must be one of:
* ``0`` — untimed
* ``1`` — absolute time
* ``2`` — Canadian byo yomi
* ``3`` — Japanese byo yomi
#### ``MainTime``
Main game time in seconds (integer, default 0)
#### ``PeriodCount``
Number of stones for Canadian byo yomi or number of periods for Japanese byo yomi (default 1)
#### ``PeriodTime``
Period duration in seconds for Canadian/Japanese byo yomi (integer, default 5)
#### ``BoardSize``
The board size (default 19)
#### ``Komi``
Komi value (fraction, default 7.5)
#### ``ConsecutivePasses``
Number of consecutive passes needed to end the game (and proceed to scoring, if a scorer is specified; default 2)
### Basic parameters
#### ``NumGames``
The number of games that should be played
#### ``TimeTolerance``
Time tolerance in seconds (microsecond resolution, default 0.000000). This tolerance is added as extra free time before logging a time violation. It only becomes relevant during the last period of the game: at the end of absolute time, during Canadian byo yomi, or during the last period of Japanese byo yomi. If an engine finishes the period within tolerance, no time violation is logged. If ``TimeTolerance`` is set to ``-1`` time keeping and checking is turned off altogether.

Note: Whether a logged time violation results in immediate loss by time is determined by the ``EnforceTime`` parameter.

#### ``EnforceTime``
Whether engines should lose by time if they exceed time controls (yes/no, default yes). It is useful to turn this off to better analyze engine behavior. On its next move, the offending engine will still see one Japanese period left or one second left of the Canadian period.

Note: No information is lost by turning EnforceTime off, as dumbarb logs all violations anyway—together with all other move times in the ``.mvtimes`` file and also separately in the ``.log`` file.
#### ``Scorer``
The name of the engine that will be asked to score the game, if the engines finish the game by ``conescutivePasses`` consecutive passes (default: none). This may be one of the playing engines or a third engine that will be launched separately. If no scorer is specified, the game will end with result "None" in the log file (N.R. in SGF).
#### ``DisableSgf``
Whether to disable saving each game as SGF (yes/no, default no)

### Wait intervals
#### ``MatchWait``
Seconds to wait before each match (fraction, default 0.0)
#### ``GameWait``
Seconds to wait before each game (fraction, default 0.5). Setting to zero may lead to slight desync of individual stderr files. A very short wait is recommended, if engine stderr is being logged.
#### ``MoveWait``
Seconds to wait before each move (fraction, default 0.0)

### GTP timeouts
GTP timeouts are hard limits. Engines exceeding them are terminated and restarted. See also the ``GtpInitialTimeout`` parameter for engines that require a longer start-up time.
#### ``GtpTimeout``
General timeout (in seconds) for all GTP commands except ``genmove`` and ``final_score`` (fraction, default 3.0)
#### ``GtpScorerTO``
GTP timeout for scoring the game (fraction, default 4.0)
#### ``GtpGenmoveExtra``
Extra seconds to add to GTP timeout for move generation—in addition to the time remaining for the player on the game clock (fraction, default 15.0). This should be generous enough to allow analysis of time violations but small enough to prevent dumbarb from hanging too long in case of engine crashes.
#### ``GtpGenmoveUntimedTO``
GTP timeout (in seconds) to use when the game is played with no time control (fraciton, default 120.0). Increase this value if the engines are to play even slower moves (dumbarb will take a longer time to detect engine crashes).

### Engine defaults
**Note:** These parameters will be overriden if they are also present in engine sections *OR* in the ``[DEFAULT]`` section, as the default section applies not only to matches, but also to engines (and the engine value will always override the match value).
#### ``Quiet``
Suppress engine standard error from appearing on screen (yes/no, default no). Logging of stderr to file is unaffected (see next parameter).
#### ``LogStdErr``
Log engine standard error to files (yes/no, default yes). On-screen display of stderr is not affected (see previous parameter). dumbarb logs stderr to individual log files for each game. A non-zero ``gameWait`` is recommended to avoid desyncing (log files containing output pertaining to a different game).
#### ``GtpInitialTimeout``
GTP timeout for the first command dumbarb sends to the engine (which is always ``list_commands``). The default is 15 or the current GtpTimeout, whichever is larger.

## Engine section
### Basic parameters
#### ``Cmd``
Command line for the engine. The strings ``{matchdir}`` and ``{name}`` will be replaced by the full path to the match folder and the engine name. This is useful to store the engine's logfile directly in the match directory, e.g. ``--logfile={matchdir}/{name}.log``. Literal curly brackets can be included in the command by doubling them (``{{`` and ``}}``). The full list of interpolated fields is:
* ``{name}`` — engine name
* ``{matchdir}`` — full path to match folder
* ``{boardsize}`` — board size
* ``{komi}`` — komi
* ``{maintime}`` — main time in seconds
* ``{periodtime}`` — period time in seconds
* ``{periodcount}`` — the number of periods/number of stones per period
* ``{timesys}`` — time system (0-3)                    
#### ``WkDir``
Working directory to start engine from (where hard-coded config files may be stored, such as ``leelaz_opencl_tuning`` or ``aq_config.txt``, etc.). Default is dumbarb's working directory.
### Miscellaneous
#### Custom commands: ``PreGame, PostGame, PreMatch, PostMatch``
These parameters may be used to send one or more custom GTP commands to the engine before/after each match and game. Multiple commands may be be specified on several lines, like this (leading whitespace stripped before sending):
```
PreGame = command_example          
          command_example2 arg1 arg2
          special-command arg1 arg2 arg3                    
```
#### ``Quiet``
Suppress engine standard error from appearing on screen (yes/no, default no). Logging of stderr to file is unaffected (see next parameter).
#### ``LogStdErr``
Log engine standard error to files (yes/no, default yes). On-screen display of stderr is not affected (see previous parameter). dumbarb logs stderr to individual log files for each game. A non-zero ``gameWait`` is recommended to avoid desyncing (log files containing output pertaining to a different game).
#### ``GtpInitialTimeout``
GTP timeout for the first command dumbarb sends to the engine (which is always ``list_commands``). The default is 15 or the current ``GtpTimeout``, whichever is larger.
