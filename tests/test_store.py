"""Tests for the SQLite storage layer."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from miniray.store import SCHEMA_VERSION, MinirayError, Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "miniray.db"
        self.store = Store(self.db_path)
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def reopen(self):
        """Simulate a program restart: close and reopen the same database."""
        self.store.close()
        self.store = Store(self.db_path)


class IdentityTests(StoreTestCase):
    def test_default_identity(self):
        ident = self.store.identity()
        self.assertEqual(ident["name"], "Ray")
        self.assertEqual(ident["system"], "Miniray")
        self.assertEqual(ident["mode"], "local-only")
        self.assertEqual(ident["approval_authority"], "Eric")
        self.assertIn("verification", ident["role"])
        self.assertTrue(ident["instance_id"])

    def test_initialize_is_idempotent(self):
        first_id = self.store.identity()["instance_id"]
        self.assertFalse(self.store.initialize())
        self.assertEqual(self.store.identity()["instance_id"], first_id)

    def test_set_and_get_config(self):
        self.store.set_config("role", "verifier")
        self.assertEqual(self.store.get_config("role"), "verifier")
        self.store.set_config("new_key", "x")
        self.assertEqual(self.store.get_config("new_key"), "x")

    def test_protected_keys_cannot_change(self):
        for key in ("instance_id", "created_at"):
            with self.assertRaises(MinirayError):
                self.store.set_config(key, "hacked")

    def test_missing_config_key(self):
        with self.assertRaises(MinirayError):
            self.store.get_config("nope")


class TaskTests(StoreTestCase):
    def test_add_and_list(self):
        a = self.store.add_task("write tests")
        b = self.store.add_task("review code")
        self.assertEqual([r["id"] for r in self.store.list_tasks()], [a, b])
        self.assertEqual(self.store.get_task(a)["status"], "open")

    def test_empty_title_rejected(self):
        with self.assertRaises(MinirayError):
            self.store.add_task("   ")

    def test_status_transitions(self):
        t = self.store.add_task("x")
        self.store.set_task_status(t, "done")
        self.assertEqual(self.store.get_task(t)["status"], "done")
        self.assertIsNotNone(self.store.get_task(t)["completed_at"])
        self.store.set_task_status(t, "open")
        self.assertIsNone(self.store.get_task(t)["completed_at"])
        self.store.set_task_status(t, "cancelled")
        self.assertEqual([r["id"] for r in self.store.list_tasks("cancelled")], [t])
        self.assertEqual(self.store.list_tasks("open"), [])

    def test_unknown_task_and_status(self):
        with self.assertRaises(MinirayError):
            self.store.get_task(999)
        t = self.store.add_task("x")
        with self.assertRaises(MinirayError):
            self.store.set_task_status(t, "maybe")
        with self.assertRaises(MinirayError):
            self.store.list_tasks("maybe")

    def test_notes_append(self):
        t = self.store.add_task("x")
        self.store.add_task_note(t, "first")
        self.store.add_task_note(t, "second")
        notes = self.store.get_task(t)["notes"].splitlines()
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].endswith("first"))
        self.assertTrue(notes[1].endswith("second"))


class ContextTests(StoreTestCase):
    def test_set_get_overwrite_delete(self):
        self.store.set_context("project", "miniray")
        self.assertEqual(self.store.get_context("project"), "miniray")
        self.store.set_context("project", "miniray v2")
        self.assertEqual(self.store.get_context("project"), "miniray v2")
        self.assertEqual(len(self.store.list_context()), 1)
        self.store.delete_context("project")
        with self.assertRaises(MinirayError):
            self.store.get_context("project")
        with self.assertRaises(MinirayError):
            self.store.delete_context("project")


class ActivityTests(StoreTestCase):
    def test_actions_are_logged_in_order(self):
        self.store.add_task("x")
        self.store.set_context("k", "v")
        kinds = [r["kind"] for r in self.store.history()]
        self.assertEqual(kinds, ["init", "task.add", "context.set"])

    def test_history_limit_and_filter(self):
        for i in range(5):
            self.store.add_task(f"t{i}")
        self.store.set_context("k", "v")
        self.assertEqual(len(self.store.history(limit=3)), 3)
        self.assertEqual(self.store.history(limit=1)[0]["kind"], "context.set")
        task_rows = self.store.history(kind="task")
        self.assertEqual(len(task_rows), 5)
        self.assertTrue(all(r["kind"] == "task.add" for r in task_rows))


class PersistenceTests(StoreTestCase):
    def test_everything_survives_reopen(self):
        instance_id = self.store.identity()["instance_id"]
        t = self.store.add_task("survive restart")
        self.store.set_task_status(t, "done")
        self.store.set_context("goal", "build foundation")
        self.store.set_config("owner", "Eric")

        self.reopen()

        self.assertEqual(self.store.identity()["instance_id"], instance_id)
        self.assertEqual(self.store.get_task(t)["status"], "done")
        self.assertEqual(self.store.get_context("goal"), "build foundation")
        self.assertEqual(self.store.get_config("owner"), "Eric")
        self.assertGreaterEqual(len(self.store.history(limit=100)), 5)

    def test_schema_version_recorded(self):
        self.assertEqual(self.store.schema_version(), SCHEMA_VERSION)

    def test_newer_schema_refused(self):
        self.store.close()
        conn = sqlite3.connect(str(self.db_path))
        with conn:
            conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
        conn.close()
        with self.assertRaises(MinirayError):
            Store(self.db_path)
        self.store = Store.__new__(Store)  # keep tearDown happy
        self.store.conn = sqlite3.connect(":memory:")


if __name__ == "__main__":
    unittest.main()
