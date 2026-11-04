import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.config_store import ConfigStore


class DynamicRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_contact_rule_overrides_global_rule(self):
        self.store.write_rules({"rules": [
            {"id": "global", "scope": "global", "instruction": "全局语气"},
            {"id": "contact", "scope": "contact", "target_id": "wxid_a", "instruction": "熟人语气"},
        ]})
        resolved = self.store.resolve_rule("wxid_a")
        self.assertEqual(resolved["instruction"], "熟人语气")

    def test_group_rule_does_not_apply_to_direct_chat(self):
        self.store.write_rules({"rules": [
            {"id": "global", "scope": "global", "instruction": "全局语气"},
            {"id": "group", "scope": "group", "target_id": "group1", "instruction": "群语气"},
        ]})
        resolved = self.store.resolve_rule("wxid_a")
        self.assertEqual(resolved["instruction"], "全局语气")

    def test_expired_temporary_rule_is_ignored(self):
        self.store.write_rules({"rules": [
            {"id": "temp", "scope": "temporary", "target_id": "wxid_a", "instruction": "临时", "expires_at": "2020-01-01T00:00:00+00:00"}
        ]})
        resolved = self.store.resolve_rule("wxid_a", now="2026-09-20T00:00:00+00:00")
        self.assertEqual(resolved["instruction"], "")

    def test_rollback_restores_previous_rule_revision(self):
        self.store.write_rules({"rules": [{"id": "r1", "scope": "global", "instruction": "第一版"}]})
        self.store.write_rules({"rules": [{"id": "r2", "scope": "global", "instruction": "第二版"}]})
        restored = self.store.rollback_rules(1)
        self.assertEqual(restored["rules"][0]["id"], "r1")


if __name__ == "__main__":
    unittest.main()
