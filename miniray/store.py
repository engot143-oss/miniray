"""SQLite persistence for Miniray.

Everything Miniray remembers lives in one SQLite file:
  meta      - internal bookkeeping (schema version)
  identity  - who this Miniray instance is (name, role, owner, ...)
  tasks     - work items with a status
  context   - key/value memory that survives restarts
  activity  - an append-only log of what happened
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from miniray import __version__

SCHEMA_VERSION = 1

TASK_STATUSES = ("open", "done", "cancelled")

# Identity keys set once at creation and never editable through config.
PROTECTED_IDENTITY_KEYS = ("instance_id", "created_at")

DEFAULT_IDENTITY = {
    "name": "Ray",
    "system": "Miniray",
    "role": "engineering, coding, verification, troubleshooting, independent checking",
    "owner": "Eric",
    "approval_authority": "Eric",
    "mode": "local-only",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identity (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'done', 'cancelled')),
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS context (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    kind   TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class MinirayError(Exception):
    """A user-facing error (bad id, bad key, ...)."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- schema -----------------------------------------------------------

    def _migrate(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row["value"]) > SCHEMA_VERSION:
                raise MinirayError(
                    f"Database schema v{row['value']} is newer than this Miniray "
                    f"(supports v{SCHEMA_VERSION}). Upgrade Miniray."
                )

    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"])

    # -- identity / config ------------------------------------------------

    def is_initialized(self) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM identity WHERE key = 'instance_id'"
        ).fetchone() is not None

    def initialize(self) -> bool:
        """Create the identity if missing. Returns True if newly created."""
        if self.is_initialized():
            return False
        values = dict(DEFAULT_IDENTITY)
        values["instance_id"] = str(uuid.uuid4())
        values["created_at"] = now()
        values["created_with_version"] = __version__
        with self.conn:
            self.conn.executemany(
                "INSERT INTO identity (key, value) VALUES (?, ?)", values.items()
            )
        self.log("init", f"identity created: {values['instance_id']}")
        return True

    def identity(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM identity ORDER BY key")
        return {r["key"]: r["value"] for r in rows}

    def get_config(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM identity WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise MinirayError(f"No config key named '{key}'.")
        return row["value"]

    def set_config(self, key: str, value: str) -> None:
        if key in PROTECTED_IDENTITY_KEYS:
            raise MinirayError(f"'{key}' is fixed at creation and cannot be changed.")
        if not key.strip():
            raise MinirayError("Config key cannot be empty.")
        with self.conn:
            self.conn.execute(
                "INSERT INTO identity (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        self.log("config", f"set {key}")

    # -- tasks ------------------------------------------------------------

    def add_task(self, title: str, notes: str = "") -> int:
        title = title.strip()
        if not title:
            raise MinirayError("Task title cannot be empty.")
        ts = now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO tasks (title, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (title, notes, ts, ts),
            )
        task_id = cur.lastrowid
        self.log("task.add", f"#{task_id} {title}")
        return task_id

    def get_task(self, task_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise MinirayError(f"No task #{task_id}.")
        return row

    def list_tasks(self, status: Optional[str] = None) -> list:
        if status is None:
            sql, args = "SELECT * FROM tasks ORDER BY id", ()
        else:
            if status not in TASK_STATUSES:
                raise MinirayError(
                    f"Unknown status '{status}'. Use one of: {', '.join(TASK_STATUSES)}."
                )
            sql, args = "SELECT * FROM tasks WHERE status = ? ORDER BY id", (status,)
        return list(self.conn.execute(sql, args))

    def set_task_status(self, task_id: int, status: str) -> None:
        if status not in TASK_STATUSES:
            raise MinirayError(f"Unknown status '{status}'.")
        self.get_task(task_id)
        ts = now()
        completed = ts if status == "done" else None
        with self.conn:
            self.conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ?",
                (status, ts, completed, task_id),
            )
        self.log(f"task.{status}", f"#{task_id}")

    def add_task_note(self, task_id: int, note: str) -> None:
        task = self.get_task(task_id)
        line = f"[{now()}] {note.strip()}"
        notes = f"{task['notes']}\n{line}" if task["notes"] else line
        with self.conn:
            self.conn.execute(
                "UPDATE tasks SET notes = ?, updated_at = ? WHERE id = ?",
                (notes, now(), task_id),
            )
        self.log("task.note", f"#{task_id}")

    # -- context (persistent memory) ---------------------------------------

    def set_context(self, key: str, value: str) -> None:
        if not key.strip():
            raise MinirayError("Context key cannot be empty.")
        with self.conn:
            self.conn.execute(
                "INSERT INTO context (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, now()),
            )
        self.log("context.set", key)

    def get_context(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM context WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise MinirayError(f"No context key named '{key}'.")
        return row["value"]

    def list_context(self) -> list:
        return list(self.conn.execute("SELECT * FROM context ORDER BY key"))

    def delete_context(self, key: str) -> None:
        with self.conn:
            cur = self.conn.execute("DELETE FROM context WHERE key = ?", (key,))
        if cur.rowcount == 0:
            raise MinirayError(f"No context key named '{key}'.")
        self.log("context.delete", key)

    # -- activity log -------------------------------------------------------

    def log(self, kind: str, detail: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO activity (ts, kind, detail) VALUES (?, ?, ?)",
                (now(), kind, detail),
            )

    def history(self, limit: int = 20, kind: Optional[str] = None) -> list:
        """Most recent activity, returned oldest-first."""
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM activity WHERE kind = ? OR kind LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (kind, kind + ".%", limit),
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)
            )
        return list(reversed(list(rows)))

    def count_activity(self, kind: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM activity WHERE kind = ?", (kind,)
        ).fetchone()[0]

    # -- summary ----------------------------------------------------------

    def status_summary(self) -> dict:
        counts = {s: 0 for s in TASK_STATUSES}
        for row in self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
        ):
            counts[row["status"]] = row["n"]
        return {
            "tasks": counts,
            "context_keys": self.conn.execute("SELECT COUNT(*) FROM context").fetchone()[0],
            "activity_entries": self.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0],
            "sessions": self.count_activity("session.start"),
        }
