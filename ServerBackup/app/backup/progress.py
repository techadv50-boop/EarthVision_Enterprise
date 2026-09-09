"""JSON progress file so the GUI can attach to a detached backup process.

Transient RUNNING / PREPARING / CANCELLED state is never reused across operations.
Each begin() installs a new cancel Event and a new operation_id.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.backup.operation import UI_IDLE, UI_STARTING, new_operation_id


def idle_progress_payload(
    *,
    master_size: int = 0,
    head_state: str = "MISSING",
    last_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical idle snapshot. No leftover stage, timer, or cancel flag."""
    return {
        "status": "idle",
        "phase": "idle",
        "kind": None,
        "message": "Ready.",
        "steps": [],
        "bytes_done": 0,
        "bytes_total": 0,
        "speed_bps": 0,
        "eta_seconds": None,
        "sha256": None,
        "backup_id": None,
        "operation_id": None,
        "error": None,
        "cancel_requested": False,
        "updated_at": None,
        "started_at": None,
        "elapsed_seconds": None,
        "operation": None,
        "application": None,
        "current_source": None,
        "current_object": None,
        "database": {},
        "overall": {
            "label": "Ready",
            "percent": None,
            "bytes_done": 0,
            "bytes_total": 0,
            "files_done": 0,
            "files_total": 0,
            "objects_done": 0,
            "objects_total": 0,
            "speed_bps": 0,
            "eta_seconds": None,
        },
        "ui_stage": UI_IDLE,
        "last_stage": UI_IDLE,
        "ssh_action": None,
        "head_state": head_state,
        "staging_state": "—",
        "master": {
            "current_size": int(master_size or 0),
            "write_bytes": 0,
            "write_objects": 0,
            "staged_bytes": 0,
            "staging_bytes": 0,
            "staging_objects": 0,
            "committed_bytes": 0,
            "head_state": head_state,
        },
        "last_result": last_result,
    }


class ProgressReporter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cancel_event = threading.Event()
        self._operation_id: str | None = None
        self._bound_cancel = False
        self._data: dict[str, Any] = idle_progress_payload()

    def bind_cancel_event(self, event: threading.Event) -> None:
        """Use this operation's Event. begin() will not replace it."""
        self._cancel_event = event
        self._bound_cancel = True

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return dict(self._data)
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return dict(self._data)

    def _dump(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._data = payload
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp.replace(self.path)
        return payload

    def replace(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Overwrite the progress file. Used for begin() and idle reset."""
        return self._dump(dict(payload))

    def write(self, **updates: Any) -> dict[str, Any]:
        current = self.read()
        writer_id = updates.get("operation_id", self._operation_id)
        file_id = current.get("operation_id")
        if writer_id and file_id and writer_id != file_id:
            return current
        if (
            self._operation_id
            and file_id is None
            and str(current.get("status") or "idle").lower() == "idle"
            and writer_id
            and writer_id != self._operation_id
        ):
            return current
        current.update(updates)
        if self._operation_id and "operation_id" not in updates:
            current["operation_id"] = self._operation_id
        return self._dump(current)

    def reset_idle(
        self,
        *,
        master_size: int = 0,
        head_state: str = "MISSING",
        last_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._cancel_event = threading.Event()
        self._operation_id = None
        return self.replace(
            idle_progress_payload(master_size=master_size, head_state=head_state, last_result=last_result)
        )

    def begin(self, **updates: Any) -> dict[str, Any]:
        """Start a live operation with a new cancel Event and a new operation_id."""
        previous = self.read()
        last_result = previous.get("last_result") if isinstance(previous.get("last_result"), dict) else None
        operation_id = str(updates.get("operation_id") or updates.get("backup_id") or new_operation_id())
        if self._bound_cancel:
            self._bound_cancel = False
        else:
            self._cancel_event = threading.Event()
        self._operation_id = operation_id
        current = idle_progress_payload(
            master_size=int((previous.get("master") or {}).get("current_size") or 0)
            if isinstance(previous.get("master"), dict)
            else 0,
            head_state=str(previous.get("head_state") or "UNCHANGED"),
            last_result=last_result,
        )
        current.update(
            {
                "status": "running",
                "phase": "starting",
                "message": "Backup started.",
                "cancel_requested": False,
                "started_at": time.time(),
                "elapsed_seconds": 0,
                "ui_stage": UI_STARTING,
                "last_stage": UI_STARTING,
                "head_state": "UNCHANGED",
                "backup_id": operation_id,
                "operation_id": operation_id,
                "overall": {
                    "label": "Preparing...",
                    "percent": None,
                    "bytes_done": 0,
                    "bytes_total": 0,
                    "files_done": 0,
                    "files_total": None,
                    "objects_done": 0,
                    "objects_total": None,
                    "speed_bps": 0,
                    "eta_seconds": None,
                },
            }
        )
        current.update(updates)
        current["cancel_requested"] = False
        current["operation_id"] = operation_id
        if not current.get("backup_id"):
            current["backup_id"] = operation_id
        return self.replace(current)

    def add_step(self, label: str, ok: bool = True, detail: str = "") -> None:
        steps = list(self.read().get("steps") or [])
        steps.append({"label": label, "ok": ok, "detail": detail})
        self.write(steps=steps)

    def cancel_requested(self) -> bool:
        if self._cancel_event.is_set():
            return True
        data = self.read()
        if str(data.get("status") or "").lower() not in {"running", "starting"}:
            return False
        if self._operation_id and data.get("operation_id") not in {None, self._operation_id}:
            return False
        if self._operation_id and data.get("operation_id") is None:
            return False
        return bool(data.get("cancel_requested"))

    def request_cancel(self, operation_id: str | None = None) -> None:
        current = self.read()
        target = operation_id or current.get("operation_id") or self._operation_id
        if not target:
            return
        if current.get("operation_id") not in {None, target}:
            return
        status = str(current.get("status") or "").lower()
        if status not in {"running", "starting"}:
            return
        if self._operation_id in {None, target}:
            self._cancel_event.set()
        self.write(cancel_requested=True, operation_id=target, message="Cancel requested…")

    def finish(
        self,
        *,
        status: str,
        ui_stage: str,
        message: str,
        error: str | None = None,
        head_state: str = "UNCHANGED",
        staging_state: str = "CLEANED",
    ) -> dict[str, Any]:
        """End an operation without wiping measured byte counts."""
        current = self.read()
        overall = current.get("overall") if isinstance(current.get("overall"), dict) else {}
        return self.write(
            status=status,
            ui_stage=ui_stage,
            phase=ui_stage.lower(),
            message=message,
            error=error,
            head_state=head_state,
            staging_state=staging_state,
            overall=overall,
            bytes_done=int(current.get("bytes_done") or overall.get("bytes_done") or 0),
            bytes_total=int(current.get("bytes_total") or overall.get("bytes_total") or 0),
            speed_bps=int(current.get("speed_bps") or 0),
        )
