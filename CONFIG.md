# dumbarb config file format

* **[Match section](#Match-section)**: [Game setup](#game-setup) | [Basic params](#basic-parameters) | [Waits](#wait-intervals) | [GTP timeouts](#gtp-timeouts) | [Engine defaults](#engine-defaults) 
* **[Engine section](#engine-section)**: [Basic params](#basic-parameters) | [Custom commands](#custom-commands) | [Misc](#miscellaneous) 


The dumbarb config file consists of sections that begin with a line containing the section name in square brackets and terminate at the start of another section or EOF. Each section contains parameters in the form ``name = value``, with each name-value pair starting on a new line (with multi-line values permitted). Parameter names are case insensitive; section names are NOT.

Each sections describes either an engine or a match between two engines, except for the ``[DEFAULT]`` section, which contains default values for all sections (both match or engine). Engine sections contain no spaces in their name, match sections contain at least one, and usually two spaces (when a match label is provided). A section can be deactivated by making its name start with ``$``.

If a parameter is omitted from the config file, dumbarb uses its internal defaults, documented below. Relying on these defaults (whenever suitable) is a good way of keeping the config file short and manageable.

A very simple config file could look like this:

```
[DEFAULT]
TimeSys = 1     # Absolute time
MainTime = 900  # 15 minutes

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
#### TimeSys
#### MainTime
#### PeriodCount
#### PeriodTime
#### BoardSize
#### Komi
#### ConsecutivePasses

### Basic parameters
#### NumGames
#### TimeTolerance
#### EnforceTime
#### Scorer
#### DisableSgf

### Wait intervals
#### MatchWait
#### GameWait
#### MoveWait

### GTP timeouts
#### GtpTimeout
#### GtpScorerTO
#### GtpGenmoveExtra
#### GtpGenmoveUntimedTO

### Engine defaults
#### Quiet
#### LogStdErr
#### GtpInitTimeout

## Engine section
### Basic parameters
#### Cmd
#### WkDir
### Custom commands
#### PreGame
#### PostGame
#### PreMatch
#### PostMatch
### Miscellaneous
#### Quiet
#### LogStdErr
#### GtpInitTimeout         
