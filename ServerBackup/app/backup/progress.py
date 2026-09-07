"""JSON progress file so the GUI can attach to a detached backup process."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ProgressReporter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {
            "status": "running",
            "phase": "starting",
            "message": "Starting…",
            "steps": [],
            "bytes_done": 0,
            "bytes_total": 0,
            "speed_bps": 0,
            "eta_seconds": None,
            "sha256": None,
            "backup_id": None,
            "error": None,
            "cancel_requested": False,
            "updated_at": None,
        }

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

    def write(self, **updates: Any) -> dict[str, Any]:
        current = self.read()
        current.update(updates)
        current["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._data = current
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
        tmp.replace(self.path)
        return current

    def add_step(self, label: str, ok: bool = True, detail: str = "") -> None:
        steps = list(self.read().get("steps") or [])
        steps.append({"label": label, "ok": ok, "detail": detail})
        self.write(steps=steps)

    def cancel_requested(self) -> bool:
        return bool(self.read().get("cancel_requested"))

    def request_cancel(self) -> None:
        self.write(cancel_requested=True, message="Cancel requested…")
