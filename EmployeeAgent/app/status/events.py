from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    SHUTDOWN = "SHUTDOWN"
    RESTART = "RESTART"
    STARTUP = "STARTUP"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNEXPECTED_OFFLINE = "UNEXPECTED_OFFLINE"
    UNEXPECTED_SHUTDOWN = "UNEXPECTED_SHUTDOWN"
    AGENT_EXIT = "AGENT_EXIT"
    AGENT_START = "AGENT_START"


CLEAN_POWER_OFF = {EventType.SHUTDOWN.value, EventType.RESTART.value, EventType.AGENT_EXIT.value}

PRESENCE_ACTIVE = "ACTIVE"
PRESENCE_INACTIVE = "INACTIVE"
PRESENCE_LOCKED = "LOCKED"
PRESENCE_LOGGED_OUT = "LOGGED_OUT"

CONN_CONNECTING = "CONNECTING"
CONN_CONNECTED = "CONNECTED"
CONN_UNAVAILABLE = "SERVER_UNAVAILABLE"


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class AuditEvent:
    timestamp: datetime
    employee_id: str
    device_id: str
    event_type: EventType
    approximate: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "time": to_iso(self.timestamp),
            "employee": self.employee_id,
            "device": self.device_id,
            "event": self.event_type.value,
            "approximate": self.approximate,
            "details": dict(self.details),
        }
