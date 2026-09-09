from __future__ import annotations

import socket
from typing import Callable

from app.constants import STARTUP_VALUE_NAME
from app.platform.base import PowerCallback, SessionCallback, StartupResult


class StubPlatform:
    """Deterministic platform used on Linux CI and in unit tests."""

    def __init__(self) -> None:
        self.idle = 0.0
        self._boot_id = "boot-1"
        self.logged_in = True
        self.locked = False
        self._startup: dict[str, str] = {}
        self._startup_error: str | None = None
        self._session_cb: SessionCallback | None = None
        self._power_cb: PowerCallback | None = None
        self._pending_session: str | None = None
        self._pending_power: str | None = None

    def idle_seconds(self) -> float:
        return self.idle

    def boot_id(self) -> str:
        return self._boot_id

    def set_boot_id(self, value: str) -> None:
        self._boot_id = value

    def hostname(self) -> str:
        try:
            return socket.gethostname() or "TEST-PC"
        except OSError:
            return "TEST-PC"

    def user_logged_in(self) -> bool:
        return self.logged_in

    def session_locked(self) -> bool:
        return self.locked

    def enable_startup(self, command: str) -> StartupResult:
        if self._startup_error:
            return StartupResult(ok=False, enabled=False, error=self._startup_error, command=command)
        self._startup[STARTUP_VALUE_NAME] = command
        return StartupResult(ok=True, enabled=True, command=command)

    def disable_startup(self) -> StartupResult:
        self._startup.pop(STARTUP_VALUE_NAME, None)
        return StartupResult(ok=True, enabled=False)

    def startup_enabled(self) -> bool:
        return STARTUP_VALUE_NAME in self._startup

    def startup_command(self) -> str | None:
        return self._startup.get(STARTUP_VALUE_NAME)

    def fail_startup(self, message: str) -> None:
        self._startup_error = message

    def notify_session(self, callback: SessionCallback | None) -> None:
        self._session_cb = callback

    def notify_power(self, callback: PowerCallback | None) -> None:
        self._power_cb = callback

    def poll_session(self) -> str | None:
        event = self._pending_session
        self._pending_session = None
        return event

    def emit_session(self, event: str) -> None:
        if event == "LOCKED":
            self.locked = True
        elif event == "UNLOCKED":
            self.locked = False
        elif event == "LOGIN":
            self.logged_in = True
        elif event == "LOGOUT":
            self.logged_in = False
            self.locked = False
        self._pending_session = event
        if self._session_cb:
            self._session_cb(event)

    def emit_power(self, event: str) -> None:
        self._pending_power = event
        if self._power_cb:
            self._power_cb(event)

    def reboot(self, new_boot_id: str = "boot-2") -> None:
        self._boot_id = new_boot_id
        self.logged_in = False
        self.locked = False
        self.idle = 0.0
