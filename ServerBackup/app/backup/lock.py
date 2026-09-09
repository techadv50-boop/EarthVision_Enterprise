"""Single-backup lock. Failed/cancelled runs never delete successful backups."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

LOCK_NAME = ".backup.lock"


class BackupAlreadyRunning(RuntimeError):
    def __init__(self, message: str = "Backup already in progress.") -> None:
        super().__init__(message)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class BackupLock:
    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination)
        self.path = self.destination / LOCK_NAME
        self._held = False

    def read(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def is_locked(self) -> bool:
        data = self.read()
        if not data:
            return False
        pid = int(data.get("pid") or 0)
        if pid and not _pid_running(pid):
            return False
        return True

    def acquire(self, *, mode: str = "manual", backup_id: str = "") -> None:
        self.destination.mkdir(parents=True, exist_ok=True)
        if self.is_locked() and not self._held:
            info = self.read() or {}
            existing_mode = info.get("mode") or "manual"
            if existing_mode == "scheduled" or mode == "scheduled":
                raise BackupAlreadyRunning(
                    "Backup already in progress. Scheduled backup skipped."
                    if mode == "scheduled"
                    else "Backup already in progress."
                )
            raise BackupAlreadyRunning("Backup already in progress.")
        payload = {
            "pid": os.getpid(),
            "mode": mode,
            "backup_id": backup_id,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        tmp = self.path.with_suffix(".lock.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self.path)
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        try:
            if self.path.is_file():
                self.path.unlink()
        except OSError:
            pass
        self._held = False

    def __enter__(self) -> "BackupLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
