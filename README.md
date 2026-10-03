# miniray

Miniray is Ray's local runtime: the computer and memory that a future AI
"brain" will run on. Version 0.2.0 adds backup and export to the v0.1.0
foundation.

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
| `backup [--to PATH]` | Save a verified copy of the database |
| `export [--to PATH]` | Write everything to a readable JSON file |
| `shell` | Interactive mode (also the default) |

Free text typed in the shell is logged as `input`. With no AI model yet,
Ray doesn't interpret it.

## Where data lives

By default `data/miniray.db` inside this folder. Override it with
`--home PATH` or the `MINIRAY_HOME` environment variable. The `data/`
folder is in `.gitignore` and is never committed.

## Backup and export

```
miniray.bat backup
miniray.bat export
```

- `backup` copies the database with SQLite's backup feature (safe even while
  another Miniray window is open), then checks the copy: SQLite integrity
  check, same instance ID, same number of tasks and context keys. If any
  check fails, the copy is deleted and an error is shown.
- `export` writes identity, tasks, context and the activity log to a UTF-8
  JSON file you can open in Notepad. It includes the Miniray version, export
  time (UTC), schema version and instance ID. It does not include file paths
  or other machine details.
- Default locations: `data/backups/miniray-YYYYMMDD-HHMMSSZ.db` and
  `data/exports/miniray-export-YYYYMMDD-HHMMSSZ.json` (times in UTC).
- `--to` accepts a file name (which must not exist yet) or an existing
  folder (a timestamped name is used inside it), e.g.
  `miniray.bat backup --to E:\miniray-backups`.
- Existing files are never overwritten.
- Backup and export only read the live database (plus one activity-log line).

> **Warning:** a backup in `data/backups/` is a local recovery copy, not a
> disaster-resistant backup. It lives in the same folder as the live
> database, so deleting or losing the Miniray folder (or the disk) loses
> both. For real protection, also copy backups elsewhere with `--to`, for
> example to a USB drive.

There is no restore or import command yet.

## Tests

```
python -m unittest discover -s tests -v
```

On Windows you can double-click `run_tests.bat`.
