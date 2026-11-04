import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.actions import ActionCenter
from wechat_ai_control.config_store import ConfigStore


class ActionCenterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.actions = ActionCenter(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_resolve_action(self):
        action = self.actions.create("send_failed", "wxid_a", "send failed", {"reason": "timeout"})
        self.assertEqual(self.actions.list()[0]["id"], action["id"])
        self.actions.dismiss(action["id"], "not needed")
        self.assertEqual(self.actions.list()[0]["status"], "dismissed")

    def test_high_risk_action_requires_confirmation(self):
        action = self.actions.create("high_risk", "wxid_a", "needs owner confirmation", {"risk": "high"})
        self.actions.require_confirmation(action["id"])
        self.assertEqual(self.actions.list()[0]["status"], "awaiting_confirmation")
        self.actions.confirm(action["id"])
        self.assertEqual(self.actions.list()[0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
