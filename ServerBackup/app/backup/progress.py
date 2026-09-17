"""JSON progress file so the GUI can attach to a detached backup process.

Transient RUNNING / PREPARING / CANCELLED state is never reused across operations.
Each begin() installs a new cancel Event and a new operation_id.

On Windows the GUI timer may have progress.json open while the worker
renames progress.json.tmp into place. That raises WinError 5 (Access is
denied) and must never abort a backup. Same-process readers use a memory
cache; disk writes retry and then fall back to an in-place write.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from app.backup.operation import UI_IDLE, UI_STARTING, new_operation_id

_CACHE_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_CACHE: dict[str, dict[str, Any]] = {}

_RETRY_WINERRORS = {5, 32}  # ACCESS_DENIED, SHARING_VIOLATION
_RETRY_ERRNOS = {11, 13, 16}  # EAGAIN, EACCES, EBUSY


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


def _cache_key(path: Path) -> str:
    return str(path)


def _path_lock(path: Path) -> threading.RLock:
    key = _cache_key(path)
    with _CACHE_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def _is_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if not isinstance(exc, OSError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror in _RETRY_WINERRORS:
        return True
    return exc.errno in _RETRY_ERRNOS


def _unique_tmp(path: Path) -> Path:
    name = f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return path.with_name(name)


def _replace_with_retry(src: Path, dest: Path, *, attempts: int = 20) -> None:
    last: Exception | None = None
    for index in range(attempts):
        try:
            os.replace(src, dest)
            return
        except OSError as exc:
            if not _is_lock_error(exc):
                raise
            last = exc
            time.sleep(0.01 * (index + 1))
    try:
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        if last is not None:
            raise last
        raise
    finally:
        try:
            src.unlink()
        except OSError:
            pass


def _write_progress_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp(path)
    text = json.dumps(payload, indent=2)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    try:
        _replace_with_retry(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_disk(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    last: Exception | None = None
    for index in range(8):
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
        except OSError as exc:
            if not _is_lock_error(exc):
                return None
            last = exc
            time.sleep(0.01 * (index + 1))
    return None if last is not None else None


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

    def _read_unlocked(self) -> dict[str, Any]:
        cached = _CACHE.get(_cache_key(self.path))
        if cached is not None:
            return dict(cached)
        disk = _read_disk(self.path)
        if disk is not None:
            _CACHE[_cache_key(self.path)] = dict(disk)
            return dict(disk)
        return dict(self._data)

    def read(self) -> dict[str, Any]:
        with _path_lock(self.path):
            return self._read_unlocked()

    def _dump_unlocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._data = payload
        _CACHE[_cache_key(self.path)] = dict(payload)
        try:
            _write_progress_file(self.path, payload)
        except OSError:
            # Memory cache is the live source of truth. A locked progress.json
            # must not abort BACKUP NOW with WinError 5.
            pass
        return payload

    def _dump(self, payload: dict[str, Any]) -> dict[str, Any]:
        with _path_lock(self.path):
            return self._dump_unlocked(dict(payload))

    def replace(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Overwrite the progress file. Used for begin() and idle reset."""
        return self._dump(dict(payload))

    def write(self, **updates: Any) -> dict[str, Any]:
        with _path_lock(self.path):
            current = self._read_unlocked()
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
            return self._dump_unlocked(current)

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
        with _path_lock(self.path):
            previous = self._read_unlocked()
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
            return self._dump_unlocked(current)

    def add_step(self, label: str, ok: bool = True, detail: str = "") -> None:
        steps = list(self.read().get("steps") or [])
        steps.append({"label": label, "ok": ok, "detail": detail})
        self.write(steps=steps)

    def cancel_requested(self) -> bool:
        if self._cancel_event.is_set():
            return True
        disk = _read_disk(self.path) or {}
        with _path_lock(self.path):
            cached = _CACHE.get(_cache_key(self.path)) or {}
            if disk.get("cancel_requested"):
                merged = dict(cached or disk)
                merged["cancel_requested"] = True
                if disk.get("operation_id"):
                    merged["operation_id"] = disk.get("operation_id")
                _CACHE[_cache_key(self.path)] = merged
                cached = merged
            data = cached or disk
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
