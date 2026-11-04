import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.command_parser import CommandParser
from wechat_ai_control.config_store import ConfigStore


class FakeGateway:
    def __init__(self, text):
        self.text = text

    def complete(self, role, messages, json_mode=False):
        return type("Result", (), {"text": self.text})()


class CommandParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_valid_rule_request(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "set_contact_rule", "payload": {"target_id": "wxid_a", "instruction": "活泼一点"}, "risk": "low", "summary": "设置联系人规则"}]}, ensure_ascii=False))
        parser = CommandParser(gateway, {"wxid_a"}, set())
        ops = parser.parse("以后对 wxid_a 活泼一点")
        self.assertEqual(ops[0].op, "set_contact_rule")
        self.assertEqual(ops[0].payload["target_id"], "wxid_a")

    def test_parse_uses_current_chat_as_default_target(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "set_contact_rule", "payload": {"instruction": "更活泼"}, "risk": "low", "summary": "设置当前联系人规则"}]}, ensure_ascii=False))
        parser = CommandParser(gateway, {"wxid_a"}, set())

        ops = parser.parse("对当前联系人活泼一点", default_target_id="wxid_a")

        self.assertEqual(ops[0].payload["target_id"], "wxid_a")

    def test_reject_unknown_operation(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "run_shell", "payload": {"cmd": "whoami"}, "risk": "high", "summary": "bad"}]}))
        parser = CommandParser(gateway, {"wxid_a"}, set())
        with self.assertRaises(ValueError):
            parser.parse("run whoami")

    def test_reject_missing_target(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "set_contact_rule", "payload": {"target_id": "missing", "instruction": "活泼"}, "risk": "low", "summary": "bad target"}]}, ensure_ascii=False))
        parser = CommandParser(gateway, {"wxid_a"}, set())
        with self.assertRaises(ValueError):
            parser.parse("以后活泼一点")

    def test_unlock_operation_is_never_allowed(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "unlock_chat", "payload": {"target_id": "wxid_a"}, "risk": "high", "summary": "unlock"}]}))
        parser = CommandParser(gateway, {"wxid_a"}, set())
        with self.assertRaises(ValueError):
            parser.parse("解锁 wxid_a")

    def test_send_message_rejects_unknown_target(self):
        gateway = FakeGateway(json.dumps({"operations": [{"op": "send_message", "payload": {"target_id": "missing", "text": "你好"}, "risk": "high", "summary": "send"}]}, ensure_ascii=False))
        parser = CommandParser(gateway, {"wxid_a"}, set())

        with self.assertRaises(ValueError):
            parser.parse("给 missing 发送消息")


if __name__ == "__main__":
    unittest.main()
