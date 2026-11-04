import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.process_supervisor import (  # noqa: E402
    ConsoleStartError,
    ProcessInfo,
    ensure_console,
    process_matches_command,
)


class FakeProcess:
    def __init__(self, pid=456):
        self.pid = pid
        self.terminated = False

    def terminate(self):
        self.terminated = True


class ProcessSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pid_path = Path(self.tmp.name) / "console.pid"
        self.url = "http://127.0.0.1:8765/api/health"
        self.command = [r"C:\Python311\pythonw.exe", r"C:\app\wechat_ai_console.py", "--port", "8765"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_healthy_console_is_reused(self):
        spawned = []

        status = ensure_console(
            self.url,
            self.command,
            pid_path=self.pid_path,
            probe=lambda _: True,
            spawn=lambda _: spawned.append(True),
        )

        self.assertFalse(status.started)
        self.assertTrue(status.healthy)
        self.assertEqual(spawned, [])

    def test_stale_pid_is_replaced_and_new_process_is_verified(self):
        self.pid_path.write_text("123", encoding="ascii")
        probes = iter([False, True])
        process = FakeProcess()

        status = ensure_console(
            self.url,
            self.command,
            pid_path=self.pid_path,
            timeout_seconds=0.2,
            poll_interval=0,
            probe=lambda _: next(probes),
            spawn=lambda _: process,
            process_lookup=lambda pid: None,
        )

        self.assertTrue(status.started)
        self.assertEqual(status.pid, 456)
        self.assertEqual(self.pid_path.read_text(encoding="ascii"), "456")

    def test_spawn_is_not_reported_ready_until_health_passes(self):
        process = FakeProcess()

        with self.assertRaises(ConsoleStartError):
            ensure_console(
                self.url,
                self.command,
                pid_path=self.pid_path,
                probe=lambda _: False,
                spawn=lambda _: process,
                process_lookup=lambda pid: None,
                timeout_seconds=0,
                poll_interval=0,
            )

        self.assertTrue(process.terminated)
        self.assertFalse(self.pid_path.exists())

    def test_unhealthy_matching_process_is_stopped_before_replacement(self):
        self.pid_path.write_text("123", encoding="ascii")
        probes = iter([False, True])
        stopped = []
        process = FakeProcess()
        info = ProcessInfo(
            pid=123,
            executable=self.command[0],
            command_line=' '.join(f'"{item}"' for item in self.command),
        )

        ensure_console(
            self.url,
            self.command,
            pid_path=self.pid_path,
            timeout_seconds=0.2,
            poll_interval=0,
            probe=lambda _: next(probes),
            spawn=lambda _: process,
            process_lookup=lambda pid: info,
            stop_process=lambda pid: stopped.append(pid),
        )

        self.assertEqual(stopped, [123])

    def test_process_match_requires_executable_and_console_script(self):
        info = ProcessInfo(
            pid=123,
            executable=r"C:\Python311\pythonw.exe",
            command_line=r'"C:\Python311\pythonw.exe" "C:\app\other.py" --port 8765',
        )

        self.assertFalse(process_matches_command(info, self.command))


if __name__ == "__main__":
    unittest.main()
