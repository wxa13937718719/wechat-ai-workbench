"""Redacted file-source and transfer transaction coordination."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Callable

from .interaction import ActivityEvent, InteractionArbiter


class FileActivitySource(str, Enum):
    HOST_UNRELATED = "host_unrelated"
    VM_WECHAT = "vm_wechat"
    VM_BRIDGE_PREPARE = "vm_bridge_prepare"
    VM_BRIDGE_COMMIT = "vm_bridge_commit"
    UNKNOWN = "unknown"


NO_LOCK_SOURCES = {FileActivitySource.HOST_UNRELATED, FileActivitySource.VM_BRIDGE_PREPARE}
LOCKING_SOURCES = {FileActivitySource.VM_WECHAT, FileActivitySource.VM_BRIDGE_COMMIT}
OUTCOMES = {"completed", "cancelled", "failed"}


def classify_file_activity(source) -> FileActivitySource:
    if isinstance(source, FileActivitySource):
        return source
    try:
        return FileActivitySource(str(source or ""))
    except ValueError:
        return FileActivitySource.UNKNOWN


@dataclass(frozen=True)
class TransferSnapshot:
    transaction_id: str | None
    source: str
    stage: str
    active: bool
    item_count: int
    started_at: float | None
    finished_at: float | None
    outcome: str | None
    error_code: str | None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["transactionId"] = payload.pop("transaction_id")
        payload["itemCount"] = payload.pop("item_count")
        payload["startedAt"] = payload.pop("started_at")
        payload["finishedAt"] = payload.pop("finished_at")
        payload["errorCode"] = payload.pop("error_code")
        return payload


class TransferCoordinator:
    """Coordinate VM-bound transfer locks without retaining file metadata."""

    def __init__(
        self,
        arbiter: InteractionArbiter,
        *,
        clock: Callable[[], float] | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        self.arbiter = arbiter
        self.clock = clock or time.monotonic
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._current: TransferSnapshot | None = None

    def _snapshot(
        self,
        transaction_id: str | None,
        source: FileActivitySource,
        stage: str,
        *,
        active: bool,
        item_count: int,
        started_at: float | None,
        finished_at: float | None = None,
        outcome: str | None = None,
        error_code: str | None = None,
    ) -> TransferSnapshot:
        return TransferSnapshot(
            transaction_id=transaction_id,
            source=source.value,
            stage=stage,
            active=active,
            item_count=max(0, int(item_count or 0)),
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            error_code=error_code,
        )

    def begin(self, source, *, item_count: int = 0, metadata=None) -> TransferSnapshot:
        del metadata
        classified = classify_file_activity(source)
        now = self.clock()
        if self._current is not None and self._current.active:
            raise ValueError("a transfer transaction is already active")
        transaction_id = str(self.id_factory())
        if classified in NO_LOCK_SOURCES:
            self._current = self._snapshot(
                transaction_id,
                classified,
                "prepared",
                active=False,
                item_count=item_count,
                started_at=now,
            )
            return self._current
        if classified in LOCKING_SOURCES:
            self.arbiter.notify(ActivityEvent(
                kind="file_transaction_started",
                source=classified.value,
                at=now,
                transaction_id=transaction_id,
            ))
            self._current = self._snapshot(
                transaction_id,
                classified,
                "locked",
                active=True,
                item_count=item_count,
                started_at=now,
            )
            return self._current

        self.arbiter.notify(ActivityEvent(kind="unknown", source="unknown", at=now))
        self._current = self._snapshot(
            transaction_id,
            FileActivitySource.UNKNOWN,
            "unknown",
            active=False,
            item_count=item_count,
            started_at=now,
            error_code="file_activity_source_unknown",
        )
        return self._current

    def finish(self, transaction_id: str, outcome: str, *, error_code: str | None = None) -> TransferSnapshot:
        if outcome not in OUTCOMES:
            raise ValueError("invalid transfer outcome")
        current = self._current
        if current is None or not current.active or current.transaction_id != transaction_id:
            raise ValueError("transfer transaction mismatch")
        now = self.clock()
        event_kind = {
            "completed": "file_transaction_finished",
            "cancelled": "file_transaction_cancelled",
            "failed": "file_transaction_failed",
        }[outcome]
        self.arbiter.notify(ActivityEvent(
            kind=event_kind,
            source=current.source,
            at=now,
            transaction_id=current.transaction_id,
        ))
        self._current = self._snapshot(
            current.transaction_id,
            FileActivitySource(current.source),
            outcome,
            active=False,
            item_count=current.item_count,
            started_at=current.started_at,
            finished_at=now,
            outcome=outcome,
            error_code=str(error_code) if error_code else None,
        )
        return self._current

    def status(self) -> dict:
        if self._current is None:
            return self._snapshot(
                None,
                FileActivitySource.HOST_UNRELATED,
                "idle",
                active=False,
                item_count=0,
                started_at=None,
            ).to_dict()
        return self._current.to_dict()
