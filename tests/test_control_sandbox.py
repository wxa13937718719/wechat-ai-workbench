import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.config_store import ConfigStore
from wechat_ai_control.runtime import RuntimeBridge


class FakeGateway:
    def complete(self, role, messages, json_mode=False):
        return type("Result", (), {"text": "沙盒回复", "provider_id": "fake", "model": "fake-model"})()


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.bridge = RuntimeBridge(store=self.store, wechat=type("W", (), {})(), state_path=Path(self.tmp.name) / "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sandbox_never_calls_send(self):
        called = {"send": False}
        def send(*args, **kwargs):
            called["send"] = True
            raise AssertionError("sandbox must not send")
        self.bridge.manual_send = send
        result = self.bridge.run_sandbox("wxid_a", "你好", FakeGateway())
        self.assertEqual(result["reply"], "沙盒回复")
        self.assertFalse(called["send"])


if __name__ == "__main__":
    unittest.main()
