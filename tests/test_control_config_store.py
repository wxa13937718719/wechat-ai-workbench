import importlib.util
import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_control" / "config_store.py"


def load_store():
    spec = importlib.util.spec_from_file_location("wechat_ai_control_config_store", STORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = load_store().ConfigStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_rule_write_is_atomic_and_versioned(self):
        payload = {"revision": 1, "rules": [{"id": "r1", "scope": "global", "instruction": "活泼一点"}]}
        saved = self.store.write_rules(payload, expected_revision=0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(self.store.read_rules()["rules"][0]["id"], "r1")

    def test_audit_event_is_persisted(self):
        event_id = self.store.audit("rule.apply", "global", "updated persona", {"revision": 2})
        rows = self.store.read_audit()
        self.assertEqual(rows[0]["id"], event_id)
        self.assertEqual(rows[0]["kind"], "rule.apply")

    def test_same_timestamp_audit_is_newest_insertion_first(self):
        self.store.audit("chat.ai.grant", "example", "grant")
        self.store.audit("chat.ai.revoke", "example", "revoke")
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.execute("UPDATE audit SET created_at = '2026-01-01T00:00:00+00:00'")
            db.commit()
        self.assertEqual([row["kind"] for row in self.store.read_audit(limit=2)], ["chat.ai.revoke", "chat.ai.grant"])

    def test_pause_flag_round_trip(self):
        self.store.set_paused(True, "manual pause")
        self.assertTrue(self.store.read_runtime()["paused"])
        self.store.set_paused(False)
        self.assertFalse(self.store.read_runtime()["paused"])

    def test_command_draft_round_trip(self):
        draft = {"id": "c1", "input_text": "以后活泼一点", "operations": [], "status": "draft"}
        self.store.create_command(draft)
        self.assertEqual(self.store.read_command("c1")["input_text"], "以后活泼一点")
        self.store.update_command("c1", "applied")
        self.assertEqual(self.store.read_command("c1")["status"], "applied")


if __name__ == "__main__":
    unittest.main()
