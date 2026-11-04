import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.interaction import ActivityEvent, InteractionArbiter
from wechat_ai_control.send_guard import SendGuard
from wechat_ai_control.vm_window import VmWindowSnapshot


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class ReadyWindowAdapter:
    def __init__(self, chat_title="测试联系人", logged_in=True):
        self.chat_title = chat_title
        self.logged_in = logged_in

    def snapshot(self):
        return VmWindowSnapshot(
            status="ready" if self.logged_in else "logged_out",
            window_id="42",
            title="Virtual WeChat",
            chat_title=self.chat_title,
            bounds={"left": 0, "top": 0, "right": 800, "bottom": 600},
            is_foreground=False,
            logged_in=self.logged_in,
            automation_ready=self.logged_in,
            reason="" if self.logged_in else "vm_logged_out",
            observed_at="2026-09-21T00:00:00+00:00",
        )


class MarkerActivitySource:
    def __init__(self):
        self.marked = 0

    def mark_automation_activity(self):
        self.marked += 1


class SendGuardTests(unittest.TestCase):
    def make_guard(self, adapter=None, activity_source=None):
        clock = FakeClock()
        arbiter = InteractionArbiter(
            adapter or ReadyWindowAdapter(),
            activity_source=activity_source,
            clock=clock,
        )
        return SendGuard(arbiter), arbiter

    def test_automation_activity_is_forwarded_to_read_only_source(self):
        source = MarkerActivitySource()
        guard, _arbiter = self.make_guard(activity_source=source)
        guard.mark_automation_activity()
        self.assertEqual(source.marked, 1)

    def test_matching_target_can_be_verified_and_released(self):
        guard, arbiter = self.make_guard()
        ticket = guard.acquire({"id": "chat-1", "name": "测试联系人"})

        self.assertTrue(ticket.allowed)
        self.assertTrue(guard.verify(ticket, {"id": "chat-1", "name": "测试联系人"}).allowed)
        guard.finish(ticket, sent=True)
        self.assertEqual(arbiter.observe().state, "AUTO_READY")

    def test_target_chat_mismatch_pauses_without_allowing_send(self):
        guard, arbiter = self.make_guard(ReadyWindowAdapter(chat_title="另一个联系人"))

        ticket = guard.acquire({"id": "chat-1", "name": "测试联系人"})

        self.assertFalse(ticket.allowed)
        self.assertEqual(ticket.reason, "target_chat_mismatch")
        self.assertEqual(arbiter.observe().state, "PAUSED_UNKNOWN")

    def test_missing_target_identity_is_rejected(self):
        guard, arbiter = self.make_guard()

        ticket = guard.acquire({"name": "测试联系人"})

        self.assertFalse(ticket.allowed)
        self.assertEqual(ticket.reason, "target_chat_missing")
        self.assertEqual(arbiter.observe().state, "AUTO_READY")

    def test_human_input_invalidates_an_acquired_ticket(self):
        guard, arbiter = self.make_guard()
        ticket = guard.acquire({"id": "chat-1", "name": "测试联系人"})
        arbiter.notify(ActivityEvent(kind="user_input", source="vm_wechat_user", at=101.0))

        decision = guard.verify(ticket, {"id": "chat-1", "name": "测试联系人"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "automation_not_allowed")
        self.assertEqual(arbiter.observe().state, "VM_HUMAN_ACTIVE")

    def test_unknown_send_result_pauses_and_clears_lease(self):
        guard, arbiter = self.make_guard()
        ticket = guard.acquire({"id": "chat-1", "name": "测试联系人"})

        guard.finish(ticket, sent=False)

        self.assertEqual(arbiter.observe().state, "PAUSED_UNKNOWN")
        self.assertFalse(guard.verify(ticket, {"id": "chat-1", "name": "测试联系人"}).allowed)

    def test_unready_window_cannot_acquire_a_ticket(self):
        guard, arbiter = self.make_guard(ReadyWindowAdapter(logged_in=False))

        ticket = guard.acquire({"id": "chat-1", "name": "测试联系人"})

        self.assertFalse(ticket.allowed)
        self.assertEqual(ticket.reason, "vm_logged_out")
        self.assertEqual(arbiter.observe().state, "PAUSED_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
