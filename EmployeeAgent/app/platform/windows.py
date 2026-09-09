"""Windows platform adapters. Imported only on Windows."""

from __future__ import annotations

import ctypes
import os
import socket
import sys
from ctypes import wintypes

from app.constants import STARTUP_VALUE_NAME
from app.platform.base import PowerCallback, SessionCallback, StartupResult

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
ENDSESSION_LOGOFF = 0x80000000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _kernel32():
    return ctypes.windll.kernel32  # type: ignore[attr-defined]


class WindowsPlatform:
    def __init__(self) -> None:
        self._session_cb: SessionCallback | None = None
        self._power_cb: PowerCallback | None = None
        self._locked = False
        self._logged_in = True

    def idle_seconds(self) -> float:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not _user32().GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick = _kernel32().GetTickCount()
        idle_ms = int(tick) - int(info.dwTime)
        if idle_ms < 0:
            idle_ms = 0
        return idle_ms / 1000.0

    def boot_id(self) -> str:
        try:
            get_tick64 = _kernel32().GetTickCount64
            get_tick64.restype = ctypes.c_ulonglong
            uptime_ms = int(get_tick64())
        except Exception:
            uptime_ms = int(_kernel32().GetTickCount())
        import time

        boot_epoch = int(time.time() - (uptime_ms / 1000.0))
        return f"boot-{boot_epoch}"

    def hostname(self) -> str:
        try:
            return socket.gethostname() or "WINDOWS-PC"
        except OSError:
            return "WINDOWS-PC"

    def user_logged_in(self) -> bool:
        return self._logged_in

    def session_locked(self) -> bool:
        return self._locked

    def enable_startup(self, command: str) -> StartupResult:
        return _write_run_key(command)

    def disable_startup(self) -> StartupResult:
        return _delete_run_key()

    def startup_enabled(self) -> bool:
        return _read_run_key() is not None

    def startup_command(self) -> str | None:
        return _read_run_key()

    def notify_session(self, callback: SessionCallback | None) -> None:
        self._session_cb = callback

    def notify_power(self, callback: PowerCallback | None) -> None:
        self._power_cb = callback

    def poll_session(self) -> str | None:
        return None

    def handle_session_notification(self, wparam: int) -> str | None:
        mapping = {
            WTS_SESSION_LOCK: "LOCKED",
            WTS_SESSION_UNLOCK: "UNLOCKED",
            WTS_SESSION_LOGON: "LOGIN",
            WTS_SESSION_LOGOFF: "LOGOUT",
        }
        event = mapping.get(int(wparam))
        if event == "LOCKED":
            self._locked = True
        elif event == "UNLOCKED":
            self._locked = False
        elif event == "LOGIN":
            self._logged_in = True
        elif event == "LOGOUT":
            self._logged_in = False
            self._locked = False
        if event and self._session_cb:
            self._session_cb(event)
        return event

    def handle_end_session(self, lparam: int, restart: bool = False) -> str:
        if int(lparam) & ENDSESSION_LOGOFF:
            event = "LOGOUT"
            self._logged_in = False
            if self._session_cb:
                self._session_cb(event)
            return event
        event = "RESTART" if restart else "SHUTDOWN"
        if self._power_cb:
            self._power_cb(event)
        return event


def _run_key():
    import winreg

    return winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")


def _write_run_key(command: str) -> StartupResult:
    try:
        import winreg

        key = _run_key()
        try:
            winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)
        finally:
            winreg.CloseKey(key)
        return StartupResult(ok=True, enabled=True, command=command)
    except OSError as exc:
        return StartupResult(ok=False, enabled=False, error=str(exc), command=command)


def _delete_run_key() -> StartupResult:
    try:
        import winreg

        key = _run_key()
        try:
            winreg.DeleteValue(key, STARTUP_VALUE_NAME)
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
        return StartupResult(ok=True, enabled=False)
    except OSError as exc:
        return StartupResult(ok=False, enabled=False, error=str(exc))


def _read_run_key() -> str | None:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        try:
            value, _typ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
        finally:
            winreg.CloseKey(key)
        return str(value)
    except OSError:
        return None


def is_windows() -> bool:
    return os.name == "nt" or sys.platform == "win32"
