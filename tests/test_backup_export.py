"""Tests for backup and export (v0.2.0)."""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from miniray import __version__
from miniray.cli import main
from miniray.store import SCHEMA_VERSION, MinirayError, Store

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TrackConnections:
    """Records every sqlite3 connection opened inside the block."""

    def __enter__(self):
        self.opened = []
        real_connect = sqlite3.connect

        def tracking_connect(*args, **kwargs):
            self.opened.append(real_connect(*args, **kwargs))
            return self.opened[-1]

        self._patch = mock.patch("miniray.store.sqlite3.connect", tracking_connect)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()

    def all_closed(self):
        for conn in self.opened:
            try:
                conn.execute("SELECT 1")
                return False
            except sqlite3.ProgrammingError:
                pass
        return True


class BackupExportTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir / "miniray.db")
        self.store.initialize()
        self.store.add_task("check the logs")
        done = self.store.add_task("write report")
        self.store.set_task_status(done, "done")
        self.store.set_context("current_focus", "backup verification")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class BackupTests(BackupExportTestCase):
    def test_backup_is_valid_copy_with_same_data(self):
        result = self.store.backup_to(self.dir / "b.db")
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["instance_id"], self.store.identity()["instance_id"])
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertTrue(result["logged"])
        self.assertEqual((result["tasks"], result["context_keys"]), (2, 1))

        with Store(self.dir / "b.db") as copy:
            self.assertEqual(copy.identity(), self.store.identity())
            self.assertEqual([dict(r) for r in copy.list_tasks()],
                             [dict(r) for r in self.store.list_tasks()])
            self.assertEqual(copy.get_context("current_focus"), "backup verification")

    def test_original_unchanged_and_still_usable(self):
        tasks_before = [dict(r) for r in self.store.list_tasks()]
        self.store.backup_to(self.dir / "b.db")
        self.assertEqual([dict(r) for r in self.store.list_tasks()], tasks_before)
        self.store.add_task("after backup")
        self.assertEqual(len(self.store.list_tasks()), 3)
        self.assertEqual(self.store.history(limit=2)[0]["kind"], "backup")

    def test_refuses_to_overwrite_existing_file(self):
        dest = self.dir / "b.db"
        dest.write_bytes(b"precious")
        with self.assertRaises(MinirayError):
            self.store.backup_to(dest)
        self.assertEqual(dest.read_bytes(), b"precious")

    def test_backup_excludes_uncommitted_changes_from_other_connection(self):
        other = sqlite3.connect(str(self.dir / "miniray.db"))
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("INSERT INTO tasks (title, created_at, updated_at) "
                          "VALUES ('uncommitted', 'x', 'x')")
            result = self.store.backup_to(self.dir / "b.db")
            other.rollback()
        finally:
            other.close()
        # The backup succeeds; only the log line is skipped while the db is locked.
        self.assertEqual(result["integrity"], "ok")
        self.assertFalse(result["logged"])
        with Store(self.dir / "b.db") as copy:
            self.assertNotIn("uncommitted", [r["title"] for r in copy.list_tasks()])

    def test_connections_closed_on_success(self):
        with TrackConnections() as t:
            self.store.backup_to(self.dir / "b.db")
        self.assertEqual(len(t.opened), 2)  # copy target + read-only verification
        self.assertTrue(t.all_closed())

    def test_failed_verification_cleans_up(self):
        dest = self.dir / "b.db"
        with TrackConnections() as t, mock.patch.object(
            self.store, "identity", return_value={"instance_id": "someone-else"}
        ):
            with self.assertRaises(MinirayError) as cm:
                self.store.backup_to(dest)
        self.assertIn("instance ID does not match", str(cm.exception))
        self.assertFalse(dest.exists(), "partial backup must be removed")
        self.assertTrue(t.all_closed())
        self.assertNotEqual(self.store.history(limit=1)[0]["kind"], "backup")

    def test_failed_copy_cleans_up(self):
        dest = self.dir / "b.db"
        with TrackConnections() as t, mock.patch.object(
            self.store, "conn", wraps=self.store.conn
        ) as conn:
            conn.backup.side_effect = sqlite3.OperationalError("disk I/O error")
            with self.assertRaises(sqlite3.OperationalError):
                self.store.backup_to(dest)
        self.assertFalse(dest.exists())
        self.assertTrue(t.all_closed())


class ExportTests(BackupExportTestCase):
    def test_export_metadata_and_contents(self):
        self.store.export_to(self.dir / "e.json")
        data = json.loads((self.dir / "e.json").read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "miniray-export")
        self.assertEqual(data["format_version"], 1)
        self.assertEqual(data["miniray_version"], __version__)
        self.assertEqual(data["schema_version"], SCHEMA_VERSION)
        self.assertTrue(data["exported_at"].endswith("+00:00"))
        self.assertEqual(data["instance_id"], self.store.identity()["instance_id"])
        self.assertEqual(data["identity"], self.store.identity())
        self.assertEqual(data["tasks"], [dict(r) for r in self.store.list_tasks()])
        self.assertEqual(data["context"], [dict(r) for r in self.store.list_context()])
        self.assertEqual([a["kind"] for a in data["activity"]][:2], ["init", "task.add"])

    def test_export_has_no_machine_specific_paths(self):
        self.store.export_to(self.dir / "e.json")
        text = (self.dir / "e.json").read_text(encoding="utf-8")
        self.assertNotIn(self.tmp.name, text)
        self.assertNotIn(self.tmp.name.replace("\\", "\\\\"), text)

    def test_export_is_utf8_and_round_trips_non_ascii(self):
        value = "café ✓ 日本語 — ñandú"
        self.store.set_context("notes", value)
        self.store.export_to(self.dir / "e.json")
        raw = (self.dir / "e.json").read_bytes()
        self.assertIn(value.encode("utf-8"), raw)  # readable, not \u-escaped
        data = json.loads(raw.decode("utf-8"))
        self.assertIn({"key": "notes", "value": value},
                      [{k: c[k] for k in ("key", "value")} for c in data["context"]])

    def test_export_is_deterministic(self):
        first, second = self.store.export_data(), self.store.export_data()
        first.pop("exported_at"), second.pop("exported_at")
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_export_does_not_change_data(self):
        before = self.store.export_data()
        self.store.export_to(self.dir / "e.json")
        after = self.store.export_data()
        self.assertEqual(after["tasks"], before["tasks"])
        self.assertEqual(after["context"], before["context"])
        self.assertEqual(after["activity"][-1]["kind"], "export")
        self.assertFalse(self.store.conn.in_transaction)

    def test_refuses_to_overwrite_existing_file(self):
        dest = self.dir / "e.json"
        dest.write_text("precious", encoding="utf-8")
        with self.assertRaises(MinirayError):
            self.store.export_to(dest)
        self.assertEqual(dest.read_text(encoding="utf-8"), "precious")

    def test_failed_write_cleans_up(self):
        dest = self.dir / "e.json"
        with mock.patch("miniray.store.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.export_to(dest)
        self.assertFalse(dest.exists())
        self.assertNotEqual(self.store.history(limit=1)[0]["kind"], "export")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = main(["--home", str(self.home), *args], inp=io.StringIO(), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_default_locations(self):
        self.run_cli("task", "add", "x")
        code, out, _ = self.run_cli("backup")
        self.assertEqual(code, 0)
        self.assertIn("integrity: ok", out)
        self.assertEqual(len(list((self.home / "backups").glob("miniray-*.db"))), 1)
        code, out, _ = self.run_cli("export")
        self.assertEqual(code, 0)
        self.assertEqual(len(list((self.home / "exports").glob("miniray-export-*.json"))), 1)

    def test_repeated_default_backups_get_unique_names(self):
        for _ in range(3):
            self.assertEqual(self.run_cli("backup")[0], 0)
        self.assertEqual(len(list((self.home / "backups").glob("*.db"))), 3)

    def test_to_folder_and_to_file(self):
        folder = self.home / "usb"
        folder.mkdir()
        self.assertEqual(self.run_cli("backup", "--to", str(folder))[0], 0)
        self.assertEqual(len(list(folder.glob("miniray-*.db"))), 1)
        target = self.home / "named" / "my-export.json"
        self.assertEqual(self.run_cli("export", "--to", str(target))[0], 0)
        self.assertTrue(target.exists())

    def test_existing_target_is_an_error(self):
        target = self.home / "taken.db"
        target.write_bytes(b"keep")
        code, _, err = self.run_cli("backup", "--to", str(target))
        self.assertEqual(code, 1)
        self.assertIn("Refusing to overwrite", err)
        self.assertEqual(target.read_bytes(), b"keep")

    def test_unwritable_destination_is_a_clean_error(self):
        blocker = self.home / "not-a-folder"
        blocker.write_bytes(b"x")  # a file where a folder would need to be
        for cmd, word in (("backup", "Backup failed"), ("export", "Export failed")):
            code, _, err = self.run_cli(cmd, "--to", str(blocker / "sub" / "out.file"))
            self.assertEqual(code, 1)
            self.assertIn(word, err)
            self.assertNotIn("Traceback", err)


class RestartTests(unittest.TestCase):
    """Data saved by one Miniray process appears in backups/exports made by another."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, *args):
        env = dict(os.environ, MINIRAY_HOME=str(self.home))
        return subprocess.run(
            [sys.executable, "-m", "miniray", *args],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_backup_and_export_from_separate_processes(self):
        self.launch("task", "add", "survives restart")
        self.launch("context", "set", "phase", "v0.2.0")
        backup = self.home / "out" / "b.db"
        export = self.home / "out" / "e.json"
        self.assertEqual(self.launch("backup", "--to", str(backup)).returncode, 0)
        self.assertEqual(self.launch("export", "--to", str(export)).returncode, 0)

        with Store(backup) as copy:
            self.assertEqual([r["title"] for r in copy.list_tasks()], ["survives restart"])
            self.assertEqual(copy.get_context("phase"), "v0.2.0")
        data = json.loads(export.read_text(encoding="utf-8"))
        self.assertEqual([t["title"] for t in data["tasks"]], ["survives restart"])
        self.assertIn("backup", [a["kind"] for a in data["activity"]])


if __name__ == "__main__":
    unittest.main()
