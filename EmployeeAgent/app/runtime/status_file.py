from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.status.events import to_iso


@dataclass
class AgentStatusSnapshot:
    running: bool
    pid: int
    employee_id: str
    device_id: str
    employee_status: str
    activity_status: str
    connection_status: str
    last_server_communication: datetime | None
    monitoring: bool
    updated_at: datetime
    config_error: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["last_server_communication"] = to_iso(self.last_server_communication)
        data["updated_at"] = to_iso(self.updated_at)
        return data


class StatusFile:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, snapshot: AgentStatusSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(snapshot.to_json(), handle, indent=2)
            handle.write("\n")
        tmp.replace(self.path)

    def read(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def is_process_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                handle = kernel32.OpenProcess(0x100000, False, pid)
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
