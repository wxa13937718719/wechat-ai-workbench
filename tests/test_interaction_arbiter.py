import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.interaction import ActivityEvent, InteractionArbiter
from wechat_ai_control.vm_window import VmWindowSnapshot


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ReadyWindowAdapter:
    def snapshot(self):
        return VmWindowSnapshot(
            status="ready",
            window_id="42",
            title="Virtual WeChat - Chat",
            chat_title="Chat",
            bounds={"left": 0, "top": 0, "right": 800, "bottom": 600},
            is_foreground=False,
            logged_in=True,
            automation_ready=True,
            reason="",
            observed_at="2026-09-21T00:00:00+00:00",
        )


class UnknownWindowAdapter:
    def snapshot(self):
        return VmWindowSnapshot(
            status="unknown",
            window_id=None,
            title="",
            chat_title="",
            bounds=None,
            is_foreground=False,
            logged_in=None,
            automation_ready=False,
            reason="vm_window_not_found",
            observed_at="2026-09-21T00:00:00+00:00",
        )


class FakeActivitySource:
    def __init__(self, events):
        self.events = list(events)

    def poll(self):
        events, self.events = self.events, []
        return events


class InteractionArbiterTests(unittest.TestCase):
    def test_observe_consumes_read_only_vm_activity_events(self):
        source = FakeActivitySource([
            ActivityEvent(kind="user_input", source="vm_wechat_user", at=100.0),
        ])
        arbiter = InteractionArbiter(
            ReadyWindowAdapter(),
            activity_source=source,
            clock=FakeClock(),
        )
        snapshot = arbiter.observe()
        self.assertEqual(snapshot.state, "VM_HUMAN_ACTIVE")
        self.assertFalse(snapshot.can_automate)

    def test_activity_observer_failure_pauses_automation(self):
        class BrokenActivitySource:
            def poll(self):
                raise RuntimeError("observer unavailable")

        arbiter = InteractionArbiter(
            ReadyWindowAdapter(),
            activity_source=BrokenActivitySource(),
            clock=FakeClock(),
        )
        snapshot = arbiter.observe()
        self.assertEqual(snapshot.state, "PAUSED_UNKNOWN")
        self.assertEqual(snapshot.reason, "vm_activity_observation_failed")
        self.assertFalse(snapshot.can_automate)

    def test_human_input_enters_active_then_returns_to_auto_after_countdown(self):
        clock = FakeClock()
        arbiter = InteractionArbiter(ReadyWindowAdapter(), idle_timeout_seconds=10, focus_grace_seconds=2, clock=clock)
        self.assertEqual(arbiter.observe().state, "AUTO_READY")
        arbiter.notify(ActivityEvent(kind="window_enter", source="vm_wechat_user"))
        self.assertEqual(arbiter.observe().state, "VM_HUMAN_ACTIVE")
        clock.advance(10)
        self.assertEqual(arbiter.observe().state, "VM_IDLE_COUNTDOWN")
        clock.advance(2)
        self.assertEqual(arbiter.observe().state, "AUTO_READY")

    def test_host_unrelated_file_activity_does_not_pause(self):
        arbiter = InteractionArbiter(ReadyWindowAdapter(), clock=FakeClock())
        snapshot = arbiter.notify(ActivityEvent(kind="file_prepare", source="host_unrelated"))
        self.assertEqual(snapshot.state, "AUTO_READY")
        self.assertTrue(snapshot.can_automate)

    def test_vm_file_transaction_returns_to_idle_countdown(self):
        clock = FakeClock()
        arbiter = InteractionArbiter(ReadyWindowAdapter(), clock=clock)
        self.assertEqual(
            arbiter.notify(ActivityEvent(kind="file_transaction_started", source="vm_wechat_user")).state,
            "VM_TRANSFER_LOCKED",
        )
        self.assertFalse(arbiter.observe().can_automate)
        self.assertEqual(
            arbiter.notify(ActivityEvent(kind="file_transaction_finished", source="vm_wechat_user")).state,
            "VM_IDLE_COUNTDOWN",
        )

    def test_automation_source_does_not_refresh_human_timer(self):
        clock = FakeClock()
        arbiter = InteractionArbiter(ReadyWindowAdapter(), idle_timeout_seconds=10, clock=clock)
        arbiter.notify(ActivityEvent(kind="window_enter", source="vm_wechat_user"))
        clock.advance(8)
        arbiter.notify(ActivityEvent(kind="automation_input", source="automation"))
        clock.advance(2)
        self.assertEqual(arbiter.observe().state, "VM_IDLE_COUNTDOWN")

    def test_user_input_revokes_automation_lease(self):
        arbiter = InteractionArbiter(ReadyWindowAdapter(), clock=FakeClock())
        lease = arbiter.acquire_automation_lease("chat-1")
        self.assertTrue(lease.granted)
        snapshot = arbiter.notify(ActivityEvent(kind="user_input", source="vm_wechat_user"))
        self.assertEqual(snapshot.state, "VM_HUMAN_ACTIVE")
        self.assertIsNone(snapshot.lease_id)
        self.assertFalse(arbiter.acquire_automation_lease("chat-1").granted)

    def test_automation_lease_expires_without_release(self):
        clock = FakeClock()
        arbiter = InteractionArbiter(ReadyWindowAdapter(), automation_lease_seconds=5, clock=clock)
        lease = arbiter.acquire_automation_lease("chat-1")
        self.assertTrue(lease.granted)
        clock.advance(5)
        snapshot = arbiter.observe()
        self.assertEqual(snapshot.state, "AUTO_READY")
        self.assertIsNone(snapshot.lease_id)
        self.assertTrue(snapshot.can_automate)

    def test_unknown_window_blocks_automation(self):
        arbiter = InteractionArbiter(UnknownWindowAdapter(), clock=FakeClock())
        snapshot = arbiter.observe()
        self.assertEqual(snapshot.state, "PAUSED_UNKNOWN")
        self.assertFalse(snapshot.can_automate)
        self.assertFalse(arbiter.acquire_automation_lease("chat-1").granted)

    def test_unknown_window_stays_paused_when_activity_arrives(self):
        arbiter = InteractionArbiter(UnknownWindowAdapter(), clock=FakeClock())
        snapshot = arbiter.notify(ActivityEvent(kind="user_input", source="vm_wechat_user"))
        self.assertEqual(snapshot.state, "PAUSED_UNKNOWN")
        self.assertFalse(snapshot.can_automate)


if __name__ == "__main__":
    unittest.main()
