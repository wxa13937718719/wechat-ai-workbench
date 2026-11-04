"""Deterministic human-versus-automation arbitration for VM WeChat."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .vm_window import VmWindowAdapter, VmWindowSnapshot


HUMAN_SOURCES = {"vm_wechat_user", "vm_wechat", "user"}
AUTOMATION_SOURCE = "automation"
TRANSFER_SOURCES = {"vm_wechat_user", "vm_wechat", "vm_bridge_commit"}


@dataclass(frozen=True)
class ActivityEvent:
    kind: str
    source: str
    at: float | None = None
    transaction_id: str | None = None


@dataclass(frozen=True)
class InteractionSnapshot:
    state: str
    reason: str
    can_automate: bool
    last_human_action_at: float | None
    idle_deadline_at: float | None
    countdown_deadline_at: float | None
    transaction_id: str | None
    lease_id: str | None
    lease_chat_id: str | None
    window: VmWindowSnapshot

    def to_dict(self, now: float | None = None) -> dict:
        current = time.monotonic() if now is None else now
        idle_remaining = None
        countdown_remaining = None
        if self.idle_deadline_at is not None:
            idle_remaining = max(0.0, self.idle_deadline_at - current)
        if self.countdown_deadline_at is not None:
            countdown_remaining = max(0.0, self.countdown_deadline_at - current)
        return {
            "state": self.state,
            "reason": self.reason,
            "canAutomate": self.can_automate,
            "lastHumanActionAt": self.last_human_action_at,
            "idleDeadlineAt": self.idle_deadline_at,
            "countdownDeadlineAt": self.countdown_deadline_at,
            "idleRemainingSeconds": idle_remaining,
            "countdownRemainingSeconds": countdown_remaining,
            "transactionId": self.transaction_id,
            "leaseId": self.lease_id,
            "leaseChatId": self.lease_chat_id,
            "window": self.window.to_dict(),
        }


@dataclass(frozen=True)
class LeaseResult:
    granted: bool
    lease_id: str | None
    reason: str
    snapshot: InteractionSnapshot


class InteractionArbiter:
    """Keep automation fail-closed while yielding to real VM user activity."""

    def __init__(
        self,
        window_adapter: VmWindowAdapter,
        *,
        idle_timeout_seconds: int = 60,
        focus_grace_seconds: int = 5,
        automation_lease_seconds: int = 20,
        pause_on_vm_file_transaction: bool = True,
        pause_on_unknown_vm_state: bool = True,
        activity_source=None,
        clock: Callable[[], float] | None = None,
    ):
        self.window_adapter = window_adapter
        self.idle_timeout_seconds = max(0, int(idle_timeout_seconds))
        self.focus_grace_seconds = max(0, int(focus_grace_seconds))
        self.automation_lease_seconds = max(1, int(automation_lease_seconds))
        self.pause_on_vm_file_transaction = bool(pause_on_vm_file_transaction)
        self.pause_on_unknown_vm_state = bool(pause_on_unknown_vm_state)
        self.activity_source = activity_source
        self.clock = clock or time.monotonic
        self._state = "AUTO_READY"
        self._reason = ""
        self._window = self._safe_window()
        self._last_human_action_at: float | None = None
        self._idle_deadline_at: float | None = None
        self._countdown_deadline_at: float | None = None
        self._transaction_id: str | None = None
        self._lease_id: str | None = None
        self._lease_chat_id: str | None = None
        self._lease_started_at: float | None = None
        self._paused_by_window = False

    def _safe_window(self) -> VmWindowSnapshot:
        try:
            snapshot = self.window_adapter.snapshot()
        except Exception:
            return VmWindowSnapshot(
                status="unknown",
                window_id=None,
                title="",
                chat_title="",
                bounds=None,
                is_foreground=False,
                logged_in=None,
                automation_ready=False,
                reason="vm_window_observation_failed",
                observed_at="",
            )
        if isinstance(snapshot, VmWindowSnapshot):
            return snapshot
        return VmWindowSnapshot(
            status="unknown",
            window_id=None,
            title="",
            chat_title="",
            bounds=None,
            is_foreground=False,
            logged_in=None,
            automation_ready=False,
            reason="vm_window_snapshot_invalid",
            observed_at="",
        )

    def _clear_lease(self):
        self._lease_id = None
        self._lease_chat_id = None
        self._lease_started_at = None

    def _set_countdown(self, now: float, reason: str):
        self._state = "VM_IDLE_COUNTDOWN"
        self._reason = reason
        self._last_human_action_at = now
        self._idle_deadline_at = None
        self._countdown_deadline_at = now + self.focus_grace_seconds
        self._transaction_id = None
        self._clear_lease()

    def _advance(self, now: float):
        if self._state == "AUTOMATION_LEASE" and self._lease_started_at is not None:
            if now >= self._lease_started_at + self.automation_lease_seconds:
                self._clear_lease()
                self._state = "AUTO_READY" if self._window.automation_ready else "PAUSED_UNKNOWN"
                self._reason = "automation_lease_expired"
        if self._state == "VM_HUMAN_ACTIVE" and self._last_human_action_at is not None:
            if now >= self._last_human_action_at + self.idle_timeout_seconds:
                self._state = "VM_IDLE_COUNTDOWN"
                self._reason = "human_idle_countdown"
                self._idle_deadline_at = None
                self._countdown_deadline_at = now + self.focus_grace_seconds
        if self._state == "VM_IDLE_COUNTDOWN" and self._countdown_deadline_at is not None:
            if now >= self._countdown_deadline_at:
                self._state = "AUTO_READY"
                self._reason = "human_idle_timeout_elapsed"
                self._last_human_action_at = None
                self._countdown_deadline_at = None

    def _refresh_window(self):
        self._window = self._safe_window()
        if self.pause_on_unknown_vm_state and not self._window.automation_ready:
            self._state = "PAUSED_UNKNOWN"
            self._reason = self._window.reason or "vm_state_not_ready"
            self._paused_by_window = True
            self._idle_deadline_at = None
            self._countdown_deadline_at = None
            self._transaction_id = None
            self._clear_lease()
        elif self._paused_by_window and self._state == "PAUSED_UNKNOWN":
            self._state = "AUTO_READY"
            self._reason = "vm_state_ready"
            self._paused_by_window = False

    def observe(self) -> InteractionSnapshot:
        now = self.clock()
        self._refresh_window()
        self._drain_activity(now)
        self._advance(now)
        return self._snapshot(now)

    def _snapshot(self, now: float | None = None) -> InteractionSnapshot:
        current = self.clock() if now is None else now
        can_automate = self._state == "AUTO_READY" and self._window.automation_ready
        return InteractionSnapshot(
            state=self._state,
            reason=self._reason,
            can_automate=can_automate,
            last_human_action_at=self._last_human_action_at,
            idle_deadline_at=self._idle_deadline_at,
            countdown_deadline_at=self._countdown_deadline_at,
            transaction_id=self._transaction_id,
            lease_id=self._lease_id,
            lease_chat_id=self._lease_chat_id,
            window=self._window,
        )

    def _drain_activity(self, now: float) -> None:
        if self.activity_source is None:
            return
        try:
            events = self.activity_source.poll() or []
        except Exception:
            self.mark_unknown("vm_activity_observation_failed")
            return
        for event in events:
            if not isinstance(event, ActivityEvent):
                self.mark_unknown("vm_activity_event_invalid")
                return
            self._apply_event(event, now)

    def _apply_event(self, event: ActivityEvent, now: float) -> InteractionSnapshot:
        if self.pause_on_unknown_vm_state and not self._window.automation_ready:
            return self._snapshot(now)
        if event.source == AUTOMATION_SOURCE:
            return self._snapshot(now)
        if event.kind == "file_transaction_started" and event.source in TRANSFER_SOURCES:
            if self.pause_on_vm_file_transaction:
                self._state = "VM_TRANSFER_LOCKED"
                self._reason = "vm_file_transaction"
                self._transaction_id = event.transaction_id or uuid.uuid4().hex
                self._idle_deadline_at = None
                self._countdown_deadline_at = None
                self._clear_lease()
            return self._snapshot(now)
        if event.kind in {"file_transaction_finished", "file_transaction_cancelled", "file_transaction_failed"} and event.source in TRANSFER_SOURCES:
            self._set_countdown(now, "vm_file_transaction_finished")
            return self._snapshot(now)
        if event.source not in HUMAN_SOURCES:
            if event.kind == "unknown":
                self._state = "PAUSED_UNKNOWN"
                self._reason = "activity_source_unknown"
                self._paused_by_window = False
                self._clear_lease()
            return self._snapshot(now)

        if event.kind in {"window_enter", "window_focus", "mouse_enter", "user_input", "click", "key", "scroll", "drag"}:
            self._state = "VM_HUMAN_ACTIVE"
            self._reason = "vm_human_activity"
            self._last_human_action_at = now
            self._idle_deadline_at = now + self.idle_timeout_seconds
            self._countdown_deadline_at = None
            self._transaction_id = None
            self._clear_lease()
        return self._snapshot(now)

    def notify(self, event: ActivityEvent) -> InteractionSnapshot:
        now = self.clock() if event.at is None else float(event.at)
        self._refresh_window()
        self._advance(now)
        return self._apply_event(event, now)

    def mark_unknown(self, reason: str) -> InteractionSnapshot:
        self._state = "PAUSED_UNKNOWN"
        self._reason = str(reason or "interaction_state_unknown")
        self._paused_by_window = False
        self._idle_deadline_at = None
        self._countdown_deadline_at = None
        self._transaction_id = None
        self._clear_lease()
        return self._snapshot()

    def acquire_automation_lease(self, chat_id: str) -> LeaseResult:
        snapshot = self.observe()
        if not snapshot.can_automate:
            return LeaseResult(False, None, snapshot.reason or "automation_not_allowed", snapshot)
        self._state = "AUTOMATION_LEASE"
        self._reason = "automation_lease_active"
        self._lease_id = uuid.uuid4().hex
        self._lease_chat_id = str(chat_id)
        self._lease_started_at = self.clock()
        snapshot = self._snapshot()
        return LeaseResult(True, self._lease_id, "", snapshot)

    def release_automation_lease(self, lease_id: str | None) -> None:
        if lease_id and lease_id == self._lease_id:
            self._clear_lease()
            self._state = "AUTO_READY" if self._window.automation_ready else "PAUSED_UNKNOWN"
            self._reason = "automation_lease_released"
