import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.wechat_mirror.sqlcipher import (  # noqa: E402
    DatabaseUnavailable,
    SchemaMismatch,
    SqlCipherReader,
    docker_runner,
)


class FakeRunner:
    def __init__(self):
        self.output = 'ok\n[{"username":"a"}]\n'
        self.calls = []
        self.error = None

    def __call__(self, args, input_text=None):
        self.calls.append((args, input_text))
        if self.error:
            raise self.error
        if "find " in " ".join(args):
            return "/profile/db_storage/db_keys.json\n"
        if args[-2:] == ["cat", "/profile/db_storage/db_keys.json"]:
            return '{"keys":{"session.db":"secret"}}'
        return self.output


class SqlCipherReaderTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.reader = SqlCipherReader(runner=self.runner)

    def test_query_rejects_non_select_sql(self):
        with self.assertRaises(ValueError):
            self.reader.query("session.db", "UPDATE SessionTable SET unread_count=0")

    def test_query_rejects_unknown_database(self):
        with self.assertRaises(ValueError):
            self.reader.query("other.db", "SELECT 1")

    def test_sqlcipher_noise_before_json_is_ignored(self):
        result = self.reader.query("session.db", "SELECT username FROM SessionTable")

        self.assertEqual(result, [{"username": "a"}])

    def test_parameters_are_bound_and_quoted_in_cli_script(self):
        self.reader.query("session.db", "SELECT username FROM SessionTable WHERE username = ?1", ("O'Reilly",))

        script = self.runner.calls[-1][1]
        self.assertIn(".parameter set ?1 'O''Reilly'", script)
        self.assertIn("WHERE username = ?1", script)

    def test_missing_schema_is_classified_without_key_leak(self):
        self.runner.output = "Error: no such table: SessionTable"

        with self.assertRaises(SchemaMismatch) as raised:
            self.reader.query("session.db", "SELECT username FROM SessionTable")

        self.assertNotIn("secret", str(raised.exception))

    def test_missing_key_file_is_database_unavailable(self):
        self.runner.error = RuntimeError("container unavailable")

        with self.assertRaises(DatabaseUnavailable):
            self.reader.query("session.db", "SELECT username FROM SessionTable")

    @unittest.skipUnless(os.name == "nt", "Windows-specific console behavior")
    def test_docker_runner_never_creates_a_console_window(self):
        completed = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        with mock.patch("wechat_ai_control.wechat_mirror.sqlcipher.subprocess.run", return_value=completed) as run:
            docker_runner(["agent-wechat", "true"])

        kwargs = run.call_args.kwargs
        self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)


if __name__ == "__main__":
    unittest.main()
