"""Standalone installation must never inherit or overwrite a live bot's state."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class ProjectCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/wechat_ai_cli.py"), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def test_init_creates_isolated_shadow_config(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("init", "--state-dir", directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((Path(directory) / "daemon.json").read_text(encoding="utf-8"))
            self.assertEqual(config["daemonMode"], "shadow")
            self.assertEqual(config["groupChatIds"], [])
            self.assertEqual(config["testChatIds"], [])
            self.assertEqual(Path(config["statePath"]), Path(directory) / "state.json")
            self.assertFalse((Path(directory) / "state.json").exists())

    def test_init_preserves_existing_config_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "daemon.json").write_text('{"daemonMode":"live"}', encoding="utf-8")
            (root / "siliconflow.json").write_text('{"apiKey":"local-test-only"}', encoding="utf-8")
            result = self.run_cli("init", "--state-dir", directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "daemon.json").read_text(), '{"daemonMode":"live"}')
            self.assertEqual((root / "siliconflow.json").read_text(), '{"apiKey":"local-test-only"}')

    def test_doctor_reports_missing_setup_without_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("doctor", "--state-dir", directory)
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ready"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_daemon_default_paths_follow_explicit_config_directory(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import wechat_ai_daemon
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "daemon.json"
            config_file.write_text('{"daemonMode":"shadow"}', encoding="utf-8")
            config = wechat_ai_daemon.load_config(config_file)
            self.assertEqual(Path(config["statePath"]), Path(directory) / "state.json")
            self.assertEqual(Path(config["controlRulesPath"]), Path(directory) / "control/rules.json")

    def test_daemon_uses_environment_key_when_local_config_is_empty(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import wechat_ai_daemon
        with tempfile.TemporaryDirectory() as directory:
            config = wechat_ai_daemon.load_config(Path(directory) / "daemon.json")
            (Path(directory) / "siliconflow.json").write_text('{"apiKey":""}', encoding="utf-8")
            with mock.patch.dict(os.environ, {"SILICONFLOW_API_KEY": "local-env-test-value"}):
                runner = wechat_ai_daemon.WeChatDaemon(config, logger=logging.getLogger("test-project-environment"))
                self.assertEqual(runner.model_config().get("apiKey"), "local-env-test-value")


if __name__ == "__main__":
    unittest.main()
