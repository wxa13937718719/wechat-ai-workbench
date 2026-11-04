import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.interaction import InteractionArbiter
from wechat_ai_control.transfer import FileActivitySource, TransferCoordinator, classify_file_activity
from wechat_ai_control.vm_window import VmWindowSnapshot


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class ReadyWindowAdapter:
    def snapshot(self):
        return VmWindowSnapshot(
            status="ready",
            window_id="42",
            title="Virtual WeChat",
            chat_title="",
            bounds={"left": 0, "top": 0, "right": 800, "bottom": 600},
            is_foreground=False,
            logged_in=True,
            automation_ready=True,
            reason="",
            observed_at="2026-09-21T00:00:00+00:00",
        )


class TransferCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.arbiter = InteractionArbiter(ReadyWindowAdapter(), clock=self.clock)
        self.coordinator = TransferCoordinator(self.arbiter, clock=self.clock, id_factory=lambda: "tx-1")

    def test_host_sources_do_not_create_a_lock(self):
        for source in ("host_unrelated", "vm_bridge_prepare"):
            with self.subTest(source=source):
                snapshot = self.coordinator.begin(source, item_count=2)
                self.assertEqual(snapshot.stage, "prepared")
                self.assertFalse(snapshot.active)
                self.assertEqual(self.arbiter.observe().state, "AUTO_READY")

    def test_vm_source_enters_transfer_lock(self):
        snapshot = self.coordinator.begin("vm_wechat", item_count=1)
        self.assertTrue(snapshot.active)
        self.assertEqual(snapshot.stage, "locked")
        self.assertEqual(self.arbiter.observe().state, "VM_TRANSFER_LOCKED")

    def test_vm_transaction_finishes_in_idle_countdown(self):
        started = self.coordinator.begin("vm_bridge_commit", item_count=1)
        finished = self.coordinator.finish(started.transaction_id, "completed")
        self.assertFalse(finished.active)
        self.assertEqual(finished.stage, "completed")
        self.assertEqual(self.arbiter.observe().state, "VM_IDLE_COUNTDOWN")

    def test_invalid_source_is_unknown_and_pauses(self):
        self.assertEqual(classify_file_activity("browser-ish"), FileActivitySource.UNKNOWN)
        snapshot = self.coordinator.begin("browser-ish")
        self.assertEqual(snapshot.source, "unknown")
        self.assertEqual(snapshot.stage, "unknown")
        self.assertEqual(self.arbiter.observe().state, "PAUSED_UNKNOWN")

    def test_classifier_accepts_a_file_activity_source(self):
        self.assertEqual(
            classify_file_activity(FileActivitySource.VM_WECHAT),
            FileActivitySource.VM_WECHAT,
        )

    def test_second_locking_transaction_is_rejected(self):
        self.coordinator.begin("vm_wechat")
        with self.assertRaisesRegex(ValueError, "already active"):
            self.coordinator.begin("vm_bridge_commit")

    def test_active_lock_cannot_be_overwritten_by_a_no_lock_source(self):
        started = self.coordinator.begin("vm_wechat")
        with self.assertRaisesRegex(ValueError, "already active"):
            self.coordinator.begin("host_unrelated")
        finished = self.coordinator.finish(started.transaction_id, "completed")
        self.assertEqual(finished.outcome, "completed")

    def test_finish_rejects_wrong_transaction_or_outcome(self):
        started = self.coordinator.begin("vm_wechat")
        with self.assertRaisesRegex(ValueError, "transaction mismatch"):
            self.coordinator.finish("tx-other", "completed")
        with self.assertRaisesRegex(ValueError, "invalid transfer outcome"):
            self.coordinator.finish(started.transaction_id, "maybe")

    def test_status_omits_path_and_filename_metadata(self):
        self.coordinator.begin(
            "vm_bridge_prepare",
            item_count=3,
            metadata={"filePath": r"C:\secret\private.pdf", "filename": "private.pdf"},
        )
        serialized = json.dumps(self.coordinator.status(), ensure_ascii=False)
        self.assertNotIn("private.pdf", serialized)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn(r"C:\secret", serialized)
        self.assertIn('"itemCount": 3', serialized)


if __name__ == "__main__":
    unittest.main()
