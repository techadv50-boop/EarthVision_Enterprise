from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.status.events import parse_datetime, to_iso


@dataclass
class PersistedState:
    boot_id: str | None = None
    last_event_type: str | None = None
    last_event_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_local_tick_at: datetime | None = None
    presence: str | None = None
    connection: str | None = None
    clean_power_off: bool = False

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["last_event_at"] = to_iso(self.last_event_at)
        data["last_heartbeat_at"] = to_iso(self.last_heartbeat_at)
        data["last_local_tick_at"] = to_iso(self.last_local_tick_at)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "PersistedState":
        if not data:
            return cls()
        return cls(
            boot_id=data.get("boot_id"),
            last_event_type=data.get("last_event_type"),
            last_event_at=parse_datetime(data.get("last_event_at")),
            last_heartbeat_at=parse_datetime(data.get("last_heartbeat_at")),
            last_local_tick_at=parse_datetime(data.get("last_local_tick_at")),
            presence=data.get("presence"),
            connection=data.get("connection"),
            clean_power_off=bool(data.get("clean_power_off")),
        )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> PersistedState:
        if not self.path.is_file():
            return PersistedState()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return PersistedState()
        if not isinstance(data, dict):
            return PersistedState()
        return PersistedState.from_json(data)

    def save(self, state: PersistedState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(state.to_json(), handle, indent=2)
            handle.write("\n")
        tmp.replace(self.path)
