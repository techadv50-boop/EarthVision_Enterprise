"""HTTP contract the agent will use with the FastAPI server."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app import __version__
from app.status.events import to_iso

HEARTBEAT_PATH = "/api/v1/agent/heartbeat"
EVENTS_PATH = "/api/v1/agent/events"
PROTOCOL_VERSION = 1


def heartbeat_url(server_url: str) -> str:
    return server_url.rstrip("/") + HEARTBEAT_PATH


def build_heartbeat_payload(
    *,
    employee_id: str,
    device_id: str,
    employee_status: str,
    activity_status: str,
    connection_status: str,
    timestamp: datetime,
    last_input_age_seconds: float | None,
    boot_id: str | None,
) -> dict[str, Any]:
    """Minimum presence payload. No keystrokes, coordinates, or media."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "employee_id": employee_id,
        "device_id": device_id,
        "status": employee_status,
        "activity_status": activity_status,
        "connection_status": connection_status,
        "timestamp": to_iso(timestamp),
        "last_input_age_seconds": last_input_age_seconds,
        "boot_id": boot_id,
        "agent_version": __version__,
    }


ALLOWED_HEARTBEAT_FIELDS = frozenset(
    {
        "protocol_version",
        "employee_id",
        "device_id",
        "status",
        "activity_status",
        "connection_status",
        "timestamp",
        "last_input_age_seconds",
        "boot_id",
        "agent_version",
    }
)
