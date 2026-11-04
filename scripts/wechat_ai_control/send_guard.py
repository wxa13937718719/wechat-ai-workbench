"""Pre-send validation and short-lived automation lease handling."""

from __future__ import annotations

from dataclasses import dataclass

from .interaction import InteractionArbiter, InteractionSnapshot


def _normalized(value) -> str:
    return " ".join(str(value or "").split()).casefold()


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str
    lease_id: str | None
    snapshot: InteractionSnapshot


@dataclass(frozen=True)
class GuardTicket:
    chat_id: str
    chat_name: str
    lease_id: str

    @property
    def allowed(self) -> bool:
        return True

    @property
    def reason(self) -> str:
        return ""


class SendGuard:
    """Verify the VM target and hold an arbiter lease around one send."""

    def __init__(self, arbiter: InteractionArbiter):
        self.arbiter = arbiter

    @staticmethod
    def _target_name(chat: dict) -> str:
        return str(chat.get("name") or chat.get("remark") or "")

    def _matches_window(self, snapshot: InteractionSnapshot, chat_name: str) -> bool:
        observed = _normalized(snapshot.window.chat_title)
        expected = _normalized(chat_name)
        return bool(observed and expected and observed == expected)

    def acquire(self, chat: dict) -> GuardDecision | GuardTicket:
        chat_id = str(chat.get("id") or "")
        if not chat_id:
            return GuardDecision(False, "target_chat_missing", None, self.arbiter.observe())
        chat_name = self._target_name(chat)
        lease = self.arbiter.acquire_automation_lease(chat_id)
        if not lease.granted:
            return GuardDecision(False, lease.reason or "automation_not_allowed", None, lease.snapshot)
        if not self._matches_window(lease.snapshot, chat_name):
            snapshot = self.arbiter.mark_unknown("target_chat_mismatch")
            return GuardDecision(False, "target_chat_mismatch", None, snapshot)
        return GuardTicket(chat_id, chat_name, lease.lease_id or "")

    def verify(self, ticket: GuardTicket | GuardDecision, chat: dict) -> GuardDecision:
        if not isinstance(ticket, GuardTicket):
            return GuardDecision(False, ticket.reason, None, self.arbiter.observe())
        snapshot = self.arbiter.observe()
        if snapshot.state != "AUTOMATION_LEASE" or snapshot.lease_id != ticket.lease_id or snapshot.lease_chat_id != ticket.chat_id:
            return GuardDecision(False, "automation_not_allowed", None, snapshot)
        if str(chat.get("id") or "") != ticket.chat_id or _normalized(self._target_name(chat)) != _normalized(ticket.chat_name):
            invalid = self.arbiter.mark_unknown("target_chat_mismatch")
            return GuardDecision(False, "target_chat_mismatch", None, invalid)
        if not self._matches_window(snapshot, ticket.chat_name):
            invalid = self.arbiter.mark_unknown("target_chat_mismatch")
            return GuardDecision(False, "target_chat_mismatch", None, invalid)
        return GuardDecision(True, "", ticket.lease_id, snapshot)

    def mark_automation_activity(self) -> None:
        source = getattr(self.arbiter, "activity_source", None)
        marker = getattr(source, "mark_automation_activity", None)
        if callable(marker):
            marker()

    def finish(self, ticket: GuardTicket | GuardDecision, *, sent: bool) -> GuardDecision:
        if not isinstance(ticket, GuardTicket):
            return GuardDecision(False, ticket.reason, None, self.arbiter.observe())
        if sent:
            self.arbiter.release_automation_lease(ticket.lease_id)
            return GuardDecision(True, "", None, self.arbiter.observe())
        snapshot = self.arbiter.mark_unknown("send_result_unknown")
        return GuardDecision(False, "send_result_unknown", None, snapshot)
