import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.config_store import ConfigStore


class RuntimeStoreTests(unittest.TestCase):
    def test_missing_runtime_has_safe_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root))
            value = store.read_runtime()
            self.assertEqual(value["interactionMode"], "vm_human_aware")
            self.assertEqual(value["idleTimeoutSeconds"], 60)

    def test_write_runtime_increments_reload_token_and_preserves_known_fields(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root))
            before = store.read_runtime()
            after = store.write_runtime({"idleTimeoutSeconds": 120}, expected_reload_token=before["reloadToken"])
            self.assertEqual(after["idleTimeoutSeconds"], 120)
            self.assertEqual(after["reloadToken"], before["reloadToken"] + 1)
            self.assertEqual(after["interactionMode"], "vm_human_aware")

    def test_stale_write_is_rejected_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root))
            current = store.write_runtime({"idleTimeoutSeconds": 120})
            with self.assertRaises(RuntimeError) as error:
                store.write_runtime({"idleTimeoutSeconds": 180}, expected_reload_token=current["reloadToken"] - 1)
            self.assertEqual(str(error.exception), "runtime_revision_conflict")
            self.assertEqual(store.read_runtime()["idleTimeoutSeconds"], 120)

    def test_invalid_json_keeps_last_valid_snapshot_and_reports_error(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root))
            store.write_runtime({"idleTimeoutSeconds": 120})
            store.runtime_path.write_text("{broken", encoding="utf-8")
            value = store.read_runtime()
            status = store.runtime_status()
            self.assertEqual(value["idleTimeoutSeconds"], 120)
            self.assertEqual(status["lastError"]["code"], "runtime_config_invalid")
            self.assertNotIn("broken", status["lastError"]["message"])

    def test_last_good_file_contains_normalized_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root))
            store.write_runtime({"idleTimeoutSeconds": 120, "unknown": "ignored"})
            saved = json.loads(store.last_good_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["idleTimeoutSeconds"], 120)
            self.assertNotIn("unknown", saved)


if __name__ == "__main__":
    unittest.main()
