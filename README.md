# miniray

Miniray is Ray's local runtime: the computer and memory that a future AI
"brain" will run on. Version 0.1.0 is the foundation only.

- Python standard library only (no installs, no internet)
- One local SQLite file holds identity, tasks, context and history
- Memory persists across restarts
- No AI model, APIs, deployment or agent-to-agent connections

## Requirements

Python 3.9 or newer. On Windows, install it from python.org and tick
"Add python.exe to PATH" (the `py` launcher also works).

## Run it

**Windows:** double-click `miniray.bat` to open the shell, or in a terminal:

```
miniray.bat status
miniray.bat task add Check the build logs
```

**Linux/macOS:** `./miniray.sh status`

**Any OS:** `python -m miniray status`

Run with no command to open the interactive shell (`ray>` prompt). Type
`help` there for the command list.

## Commands

| Command | What it does |
|---|---|
| `status` | Summary: tasks, memory, sessions |
| `whoami` | Show Ray's identity |
| `config list` / `get KEY` / `set KEY VALUE` | View or change identity values |
| `task add TITLE` | Add a task |
| `task list [--status open\|done\|cancelled]` | List tasks |
| `task show\|done\|cancel\|reopen ID` | Work with one task |
| `task note ID TEXT` | Add a timestamped note to a task |
| `context set KEY VALUE` / `get KEY` / `list` / `delete KEY` | Persistent memory |
| `history [-n N] [--kind KIND]` | Recent activity log |
| `shell` | Interactive mode (also the default) |

Free text typed in the shell is logged as `input`. With no AI model yet,
Ray doesn't interpret it.

## Where data lives

By default `data/miniray.db` inside this folder. Override it with
`--home PATH` or the `MINIRAY_HOME` environment variable. The `data/`
folder is in `.gitignore` and is never committed.

## Tests

```
python -m unittest discover -s tests -v
```

On Windows you can double-click `run_tests.bat`.
