"""Per-operation lifecycle. One active worker; cancel state never leaks."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.utils.timeutil import backup_id_now

KIND_BACKUP = "backup"
KIND_DRY_RUN = "dry_run"
KIND_RESTORE = "restore"
KIND_REBUILD = "rebuild"

UI_IDLE = "IDLE"
UI_STARTING = "STARTING"
UI_CONNECTING = "CONNECTING"
UI_DISCOVERING = "DISCOVERING"
UI_INVENTORY = "INVENTORY"
UI_DELTA = "DELTA"
UI_HASHING = "HASHING"
UI_DATABASE = "DATABASE"
UI_TRANSFERRING = "TRANSFERRING"
UI_VERIFYING = "VERIFYING"
UI_COMMITTING = "COMMITTING"
UI_SUCCESS = "SUCCESS"
UI_FAILED = "FAILED"
UI_CANCELLED = "CANCELLED"

UI_STAGES = (
    UI_IDLE,
    UI_STARTING,
    UI_CONNECTING,
    UI_DISCOVERING,
    UI_INVENTORY,
    UI_DELTA,
    UI_HASHING,
    UI_DATABASE,
    UI_TRANSFERRING,
    UI_VERIFYING,
    UI_COMMITTING,
    UI_SUCCESS,
    UI_FAILED,
    UI_CANCELLED,
)

TERMINAL_STAGES = frozenset({UI_SUCCESS, UI_FAILED, UI_CANCELLED, UI_IDLE})
ACTIVE_KINDS = frozenset({KIND_BACKUP, KIND_DRY_RUN, KIND_RESTORE, KIND_REBUILD})


def new_operation_id() -> str:
    return f"{backup_id_now()}-{uuid.uuid4().hex[:8]}"


@dataclass
class OperationState:
    """Mutable while running; becomes immutable history after finish()."""

    operation_id: str
    kind: str
    cancel_event: threading.Event
    started_at: float
    ui_stage: str = UI_STARTING
    worker: Any | None = None
    result: dict[str, Any] | None = None
    finished: bool = False
    frozen_elapsed: int | None = None

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def finish(self, result: dict[str, Any] | None = None, *, elapsed: int | None = None) -> None:
        self.finished = True
        self.result = dict(result or {})
        if elapsed is not None:
            self.frozen_elapsed = elapsed


class OperationAlreadyActive(RuntimeError):
    def __init__(self, message: str = "An operation is already in progress.") -> None:
        super().__init__(message)


class OperationRegistry:
    """Exactly one active backup / dry-run / restore / rebuild."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: OperationState | None = None
        self._history: list[OperationState] = []

    def active(self) -> OperationState | None:
        with self._lock:
            if self._active is None or self._active.finished:
                return None
            return self._active

    def active_id(self) -> str | None:
        op = self.active()
        return None if op is None else op.operation_id

    def try_start(self, kind: str, operation_id: str | None = None) -> OperationState | None:
        if kind not in ACTIVE_KINDS:
            raise ValueError(f"Unknown operation kind: {kind}")
        with self._lock:
            if self._active is not None and not self._active.finished:
                return None
            state = OperationState(
                operation_id=operation_id or new_operation_id(),
                kind=kind,
                cancel_event=threading.Event(),
                started_at=time.time(),
                ui_stage=UI_STARTING,
            )
            self._active = state
            return state

    def matches(self, operation_id: str | None) -> bool:
        if not operation_id:
            return False
        op = self.active()
        return op is not None and op.operation_id == operation_id

    def request_cancel(self, operation_id: str | None = None) -> bool:
        op = self.active()
        if op is None:
            return False
        if operation_id and op.operation_id != operation_id:
            return False
        op.request_cancel()
        return True

    def finish(self, operation_id: str, result: dict[str, Any] | None = None) -> OperationState | None:
        with self._lock:
            op = self._active
            if op is None or op.operation_id != operation_id:
                return None
            elapsed = max(0, int(time.time() - op.started_at))
            op.finish(result, elapsed=elapsed)
            self._history.append(op)
            self._active = None
            return op

    def ignore_event(self, operation_id: str | None) -> bool:
        """True when a worker/Qt signal must not update the live panel."""
        return not self.matches(operation_id)
