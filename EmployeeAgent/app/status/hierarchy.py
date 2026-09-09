"""Final status hierarchy for workstation availability."""

from __future__ import annotations

from app.status.events import (
    CONN_CONNECTING,
    CONN_UNAVAILABLE,
    PRESENCE_INACTIVE,
    PRESENCE_LOCKED,
    PRESENCE_LOGGED_OUT,
)


def workstation_status(
    *,
    lifecycle: str | None,
    presence: str,
    connection: str,
    config_error: str | None = None,
) -> str:
    """Single employee status used by heartbeats and the audit trail.

    Precedence:
    SHUTDOWN / STARTUP / OFFLINE / LOGGED OUT / LOCKED / INACTIVE / ACTIVE
    """
    if config_error:
        return "ERROR"
    if lifecycle == "SHUTDOWN":
        return "SHUTDOWN"
    if lifecycle == "STARTUP" and presence == PRESENCE_LOGGED_OUT:
        return "STARTUP"
    if connection == CONN_UNAVAILABLE:
        return "OFFLINE"
    if presence == PRESENCE_LOGGED_OUT:
        return "LOGGED_OUT"
    if presence == PRESENCE_LOCKED:
        return "LOCKED"
    if presence == PRESENCE_INACTIVE:
        return "INACTIVE"
    return "ACTIVE"


def tray_indicator(
    *,
    connection: str,
    config_error: str | None,
    monitoring: bool,
) -> str:
    """System-tray color/state. Does not include keystrokes or other private data."""
    if config_error:
        return "warning"
    if not monitoring:
        return "warning"
    if connection == CONN_CONNECTING:
        return "yellow"
    if connection == CONN_UNAVAILABLE:
        return "red"
    return "green"
