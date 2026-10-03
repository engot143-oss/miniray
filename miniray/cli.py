"""Command-line interface for Miniray.

Run `python -m miniray --help` for commands, or `python -m miniray` with no
arguments to open the interactive shell.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Optional, TextIO

from miniray import __version__
from miniray.store import MinirayError, Store

DB_FILENAME = "miniray.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_home(cli_home: Optional[str]) -> Path:
    """Where Miniray keeps its data: --home, then MINIRAY_HOME, then ./data."""
    if cli_home:
        return Path(cli_home).expanduser()
    env = os.environ.get("MINIRAY_HOME")
    if env:
        return Path(env).expanduser()
    return PROJECT_ROOT / "data"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="miniray",
        description="Miniray local runtime. Run with no command to open the shell.",
    )
    p.add_argument("--home", help="data folder (default: MINIRAY_HOME or ./data)")
    p.add_argument("--version", action="version", version=f"miniray {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("init", help="create Miniray's identity and database")
    sub.add_parser("status", help="show a summary of Miniray's state")
    sub.add_parser("whoami", help="show Miniray's identity")
    sub.add_parser("shell", help="open the interactive shell")

    cfg = sub.add_parser("config", help="view or change identity/config values")
    cfg_sub = cfg.add_subparsers(dest="action", metavar="<action>", required=True)
    cfg_sub.add_parser("list", help="show all config values")
    g = cfg_sub.add_parser("get", help="show one config value")
    g.add_argument("key")
    s = cfg_sub.add_parser("set", help="change a config value")
    s.add_argument("key")
    s.add_argument("value")

    task = sub.add_parser("task", help="manage tasks")
    t_sub = task.add_subparsers(dest="action", metavar="<action>", required=True)
    a = t_sub.add_parser("add", help="add a task")
    a.add_argument("title", nargs="+")
    ls = t_sub.add_parser("list", help="list tasks")
    ls.add_argument("--status", choices=["open", "done", "cancelled"])
    for name, help_text in (
        ("show", "show one task"),
        ("done", "mark a task done"),
        ("cancel", "cancel a task"),
        ("reopen", "reopen a task"),
    ):
        x = t_sub.add_parser(name, help=help_text)
        x.add_argument("id", type=int)
    n = t_sub.add_parser("note", help="append a note to a task")
    n.add_argument("id", type=int)
    n.add_argument("text", nargs="+")

    ctx = sub.add_parser("context", help="persistent memory (key/value)")
    c_sub = ctx.add_subparsers(dest="action", metavar="<action>", required=True)
    cs = c_sub.add_parser("set", help="remember a value")
    cs.add_argument("key")
    cs.add_argument("value", nargs="+")
    cg = c_sub.add_parser("get", help="recall a value")
    cg.add_argument("key")
    c_sub.add_parser("list", help="show everything remembered")
    cd = c_sub.add_parser("delete", help="forget a value")
    cd.add_argument("key")

    h = sub.add_parser("history", help="show recent activity")
    h.add_argument("-n", "--limit", type=int, default=20)
    h.add_argument("--kind", help="filter, e.g. task or context.set")

    return p


# -- command handlers -------------------------------------------------------


def cmd_init(store: Store, args, out: TextIO) -> int:
    # Identity is created automatically before any command runs; init just reports it.
    ident = store.identity()
    print(f"Miniray ready. Instance {ident['instance_id']}", file=out)
    print(f"Data: {store.db_path}", file=out)
    return 0


def cmd_status(store: Store, args, out: TextIO) -> int:
    ident = store.identity()
    s = store.status_summary()
    t = s["tasks"]
    print(f"{ident.get('name', '?')} ({ident.get('system', 'Miniray')}) v{__version__}", file=out)
    print(f"  mode:      {ident.get('mode', '?')}", file=out)
    print(f"  data:      {store.db_path}", file=out)
    print(f"  tasks:     {t['open']} open, {t['done']} done, {t['cancelled']} cancelled", file=out)
    print(f"  context:   {s['context_keys']} keys", file=out)
    print(f"  sessions:  {s['sessions']}", file=out)
    print(f"  activity:  {s['activity_entries']} entries", file=out)
    return 0


def cmd_whoami(store: Store, args, out: TextIO) -> int:
    for key, value in store.identity().items():
        print(f"{key:22} {value}", file=out)
    return 0


def cmd_config(store: Store, args, out: TextIO) -> int:
    if args.action == "list":
        return cmd_whoami(store, args, out)
    if args.action == "get":
        print(store.get_config(args.key), file=out)
        return 0
    store.set_config(args.key, args.value)
    print(f"{args.key} = {args.value}", file=out)
    return 0


def _print_task_line(row, out: TextIO) -> None:
    mark = {"open": "[ ]", "done": "[x]", "cancelled": "[-]"}[row["status"]]
    print(f"{mark} #{row['id']:<4} {row['title']}", file=out)


def cmd_task(store: Store, args, out: TextIO) -> int:
    action = args.action
    if action == "add":
        task_id = store.add_task(" ".join(args.title))
        print(f"Added task #{task_id}", file=out)
    elif action == "list":
        rows = store.list_tasks(args.status)
        if not rows:
            print("No tasks.", file=out)
        for row in rows:
            _print_task_line(row, out)
    elif action == "show":
        row = store.get_task(args.id)
        _print_task_line(row, out)
        print(f"  created:   {row['created_at']}", file=out)
        print(f"  updated:   {row['updated_at']}", file=out)
        if row["completed_at"]:
            print(f"  completed: {row['completed_at']}", file=out)
        if row["notes"]:
            print("  notes:", file=out)
            for line in row["notes"].splitlines():
                print(f"    {line}", file=out)
    elif action == "note":
        store.add_task_note(args.id, " ".join(args.text))
        print(f"Note added to task #{args.id}", file=out)
    else:
        status = {"done": "done", "cancel": "cancelled", "reopen": "open"}[action]
        store.set_task_status(args.id, status)
        print(f"Task #{args.id} is now {status}", file=out)
    return 0


def cmd_context(store: Store, args, out: TextIO) -> int:
    if args.action == "set":
        store.set_context(args.key, " ".join(args.value))
        print(f"Remembered '{args.key}'", file=out)
    elif args.action == "get":
        print(store.get_context(args.key), file=out)
    elif args.action == "list":
        rows = store.list_context()
        if not rows:
            print("Nothing remembered yet.", file=out)
        for row in rows:
            print(f"{row['key']} = {row['value']}", file=out)
    else:
        store.delete_context(args.key)
        print(f"Forgot '{args.key}'", file=out)
    return 0


def cmd_history(store: Store, args, out: TextIO) -> int:
    rows = store.history(limit=max(1, args.limit), kind=args.kind)
    if not rows:
        print("No activity.", file=out)
    for row in rows:
        detail = f"  {row['detail']}" if row["detail"] else ""
        print(f"{row['ts']}  {row['kind']:<14}{detail}", file=out)
    return 0


HANDLERS = {
    "init": cmd_init,
    "status": cmd_status,
    "whoami": cmd_whoami,
    "config": cmd_config,
    "task": cmd_task,
    "context": cmd_context,
    "history": cmd_history,
}

SHELL_HELP = """\
Commands (same as the command line, without 'miniray'):
  status | whoami | history [-n N] [--kind K]
  task add <title> | task list [--status S] | task show|done|cancel|reopen <id>
  task note <id> <text>
  context set <key> <value> | context get|delete <key> | context list
  config list | config get <key> | config set <key> <value>
  help | exit
Anything else is logged as input (no AI brain installed yet)."""


def run_command(store: Store, args, out: TextIO, err: TextIO) -> int:
    try:
        return HANDLERS[args.command](store, args, out)
    except MinirayError as e:
        print(f"Error: {e}", file=err)
        return 1


def handle_input(store: Store, line: str, out: TextIO) -> None:
    """Free-form input. With no AI model yet, Miniray records it and says so."""
    store.log("input", line)
    print("Logged. No AI brain installed yet, so I can't interpret free text.", file=out)
    print("Type 'help' to see commands.", file=out)


def run_shell(store: Store, parser: argparse.ArgumentParser,
              inp: TextIO, out: TextIO, err: TextIO) -> int:
    ident = store.identity()
    interactive = inp.isatty()
    print(f"{ident.get('name', 'Ray')} ({ident.get('system', 'Miniray')}) shell. "
          "Type 'help' or 'exit'.", file=out)
    while True:
        if interactive:
            out.write("ray> ")
            out.flush()
        line = inp.readline()
        if not line:  # EOF
            break
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line in ("help", "?"):
            print(SHELL_HELP, file=out)
            continue
        try:
            words = shlex.split(line)
        except ValueError as e:
            print(f"Error: {e}", file=err)
            continue
        if words[0] not in HANDLERS:
            handle_input(store, line, out)
            continue
        try:
            args = parser.parse_args(words)
        except SystemExit:
            continue  # argparse already printed the problem
        run_command(store, args, out, err)
    store.log("session.end", "shell")
    return 0


def main(argv: Optional[list] = None, inp: TextIO = None,
         out: TextIO = None, err: TextIO = None) -> int:
    inp = inp or sys.stdin
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "shell"

    try:
        store = Store(resolve_home(args.home) / DB_FILENAME)
    except MinirayError as e:
        print(f"Error: {e}", file=err)
        return 1

    with store:
        if store.initialize():
            print(f"First run: created Miniray identity in {store.db_path}", file=out)
        store.log("session.start", command)
        if command == "shell":
            return run_shell(store, parser, inp, out, err)
        return run_command(store, args, out, err)


if __name__ == "__main__":
    sys.exit(main())
