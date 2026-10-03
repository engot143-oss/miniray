"""Tests for the command line, including real restarts in separate processes."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from miniray.cli import main

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        code = main(["--home", self.home, *args], inp=io.StringIO(stdin), out=out, err=err)
        return code, out.getvalue(), err.getvalue()


class CommandTests(CliTestCase):
    def test_first_run_creates_identity_once(self):
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn("First run", out)
        _, out2, _ = self.run_cli("init")
        self.assertNotIn("First run", out2)

    def test_task_workflow(self):
        self.assertIn("#1", self.run_cli("task", "add", "check", "the", "logs")[1])
        self.assertIn("[ ] #1", self.run_cli("task", "list")[1])
        self.run_cli("task", "note", "1", "looked", "fine")
        self.run_cli("task", "done", "1")
        _, out, _ = self.run_cli("task", "show", "1")
        self.assertIn("[x] #1", out)
        self.assertIn("check the logs", out)
        self.assertIn("looked fine", out)
        self.assertIn("No tasks.", self.run_cli("task", "list", "--status", "open")[1])

    def test_errors_return_nonzero(self):
        code, _, err = self.run_cli("task", "done", "42")
        self.assertEqual(code, 1)
        self.assertIn("No task #42", err)
        code, _, err = self.run_cli("config", "set", "instance_id", "x")
        self.assertEqual(code, 1)

    def test_context_and_config(self):
        self.run_cli("context", "set", "focus", "runtime", "first")
        self.assertEqual(self.run_cli("context", "get", "focus")[1].strip(), "runtime first")
        self.run_cli("config", "set", "name", "Ray")
        self.assertIn("Ray", self.run_cli("whoami")[1])

    def test_status_and_history(self):
        self.run_cli("task", "add", "a")
        _, out, _ = self.run_cli("status")
        self.assertIn("1 open", out)
        self.assertIn("local-only", out)
        _, hist, _ = self.run_cli("history", "--kind", "task")
        self.assertIn("task.add", hist)


class ShellTests(CliTestCase):
    def test_shell_runs_commands_and_logs_free_text(self):
        script = "task add from shell\ntask list\nhello ray\nbogus --flag\nexit\n"
        code, out, _ = self.run_cli("shell", stdin=script)
        self.assertEqual(code, 0)
        self.assertIn("Added task #1", out)
        self.assertIn("from shell", out)
        self.assertIn("No AI brain installed yet", out)
        _, hist, _ = self.run_cli("history", "--kind", "input")
        self.assertIn("hello ray", hist)
        self.assertIn("bogus --flag", hist)

    def test_shell_survives_bad_arguments(self):
        script = "task done notanumber\ntask add still works\n"
        with contextlib.redirect_stderr(io.StringIO()) as argparse_err:
            code, out, _ = self.run_cli(stdin=script)  # no command = shell
        self.assertIn("invalid int value", argparse_err.getvalue())
        self.assertEqual(code, 0)
        self.assertIn("Added task #1", out)


class RestartTests(CliTestCase):
    """Runs Miniray as a real separate program each time, like a user would."""

    def launch(self, *args):
        env = dict(os.environ, MINIRAY_HOME=self.home)
        return subprocess.run(
            [sys.executable, "-m", "miniray", *args],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_state_persists_across_processes(self):
        self.assertEqual(self.launch("task", "add", "persist me").returncode, 0)
        self.launch("context", "set", "last_topic", "restart test")
        first_identity = self.launch("config", "get", "instance_id").stdout.strip()

        # Each launch above was a separate process that exited. Check memory now.
        self.assertIn("persist me", self.launch("task", "list").stdout)
        self.assertEqual(self.launch("context", "get", "last_topic").stdout.strip(),
                         "restart test")
        self.assertEqual(self.launch("config", "get", "instance_id").stdout.strip(),
                         first_identity)
        # 7 launches in total, including this status call.
        self.assertIn("sessions:  7", self.launch("status").stdout)


if __name__ == "__main__":
    unittest.main()
