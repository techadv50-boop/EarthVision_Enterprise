from __future__ import annotations

import socket
from dataclasses import asdict, dataclass, field
from typing import Any

from app.constants import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_INACTIVITY_SECONDS,
    DEFAULT_OFFLINE_AFTER_SECONDS,
    DEFAULT_POLL_SECONDS,
)


def default_device_id() -> str:
    try:
        name = socket.gethostname().strip()
    except OSError:
        name = ""
    return name or "WORKSTATION"


@dataclass
class AgentConfig:
    employee_id: str = ""
    device_id: str = field(default_factory=default_device_id)
    server_url: str = "http://127.0.0.1:8000"
    inactivity_timeout_seconds: int = DEFAULT_INACTIVITY_SECONDS
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    offline_after_seconds: int = DEFAULT_OFFLINE_AFTER_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_SECONDS
    password_hash: str = ""
    start_with_windows: bool = True
    heartbeat_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentConfig":
        if not data:
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def needs_setup(self) -> bool:
        return not bool(self.password_hash) or not bool(self.employee_id.strip())
