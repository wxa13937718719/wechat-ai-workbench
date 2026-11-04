import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

DAEMON = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_daemon.py"
spec = importlib.util.spec_from_file_location("wechat_ai_daemon_runtime_config", DAEMON)
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)


class FakeCore:
    def __init__(self):
        self.active = None

    def writer_status(self, path):
        if not Path(path).exists():
            return None
        return json.loads(Path(path).read_text(encoding="utf-8"))


class DaemonRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.logger = daemon.logging.getLogger("daemon-runtime-config-test")
        self.logger.handlers[:] = [daemon.logging.NullHandler()]

    def tearDown(self):
        self.logger.handlers[:] = []

    def test_reload_reads_runtime_settings_without_changing_send_mode(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            config = {
                "statePath": str(root_path / "state.json"),
                "activeWriterPath": str(root_path / "active.json"),
                "stopFlagPath": str(root_path / "stop"),
                "heartbeatPath": str(root_path / "heartbeat"),
                "logPath": str(root_path / "daemon.log"),
                "controlRuntimePath": str(root_path / "control" / "runtime.json"),
                "controlRulesPath": str(root_path / "control" / "rules.json"),
                "siliconflowConfigPath": str(root_path / "siliconflow.json"),
                "personaPath": str(root_path / "persona.md"),
                "daemonMode": "live",
                "errorBackoffSeconds": 1,
                "maxBackoffSeconds": 2,
                "pollIntervalSeconds": 30,
                "perChatMinIntervalSeconds": 8,
                "perChatHourlyLimit": 30,
            }
            runtime = Path(config["controlRuntimePath"])
            runtime.parent.mkdir(parents=True)
            runtime.write_text(json.dumps({"reloadToken": 4, "idleTimeoutSeconds": 120}), encoding="utf-8")
            runner = daemon.WeChatDaemon(config, core=FakeCore(), logger=self.logger)
            loaded = runner.reload_control_config()
            self.assertEqual(loaded["idleTimeoutSeconds"], 120)
            self.assertEqual(runner.config["daemonMode"], "live")
            self.assertEqual(runner.config_status()["revision"], 4)

    def test_invalid_runtime_config_keeps_last_effective_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime = root_path / "control" / "runtime.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_text(json.dumps({"reloadToken": 4, "idleTimeoutSeconds": 120}), encoding="utf-8")
            runner = daemon.WeChatDaemon({
                "controlRuntimePath": str(runtime),
                "daemonMode": "live",
                "errorBackoffSeconds": 1,
                "maxBackoffSeconds": 2,
                "logPath": str(root_path / "daemon.log"),
                "activeWriterPath": str(root_path / "active.json"),
                "perChatMinIntervalSeconds": 8,
                "perChatHourlyLimit": 30,
            }, core=FakeCore(), logger=self.logger)
            first = runner.reload_control_config()
            runtime.write_text("{broken", encoding="utf-8")
            second = runner.reload_control_config()
            self.assertEqual(first["idleTimeoutSeconds"], 120)
            self.assertEqual(second["idleTimeoutSeconds"], 120)
            self.assertEqual(runner.config_status()["source"], "last-good")
            self.assertEqual(runner.config_status()["lastError"]["code"], "runtime_config_invalid")

    def test_active_writer_metadata_contains_only_runtime_summary(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime = root_path / "control" / "runtime.json"
            active = root_path / "active.json"
            runtime.parent.mkdir(parents=True)
            runtime.write_text(json.dumps({"reloadToken": 7, "idleTimeoutSeconds": 90}), encoding="utf-8")
            active.write_text(json.dumps({"pid": 1234, "startedAt": "now"}), encoding="utf-8")
            runner = daemon.WeChatDaemon({
                "controlRuntimePath": str(runtime),
                "activeWriterPath": str(active),
                "daemonMode": "live",
                "errorBackoffSeconds": 1,
                "maxBackoffSeconds": 2,
                "logPath": str(root_path / "daemon.log"),
                "perChatMinIntervalSeconds": 8,
                "perChatHourlyLimit": 30,
            }, core=FakeCore(), logger=self.logger)
            runner.reload_control_config()
            runner._update_active_writer_metadata()
            metadata = json.loads(active.read_text(encoding="utf-8"))
            self.assertEqual(metadata["controlConfigRevision"], 7)
            self.assertEqual(metadata["idleTimeoutSeconds"], 90)
            self.assertNotIn("apiKey", json.dumps(metadata))


if __name__ == "__main__":
    unittest.main()
