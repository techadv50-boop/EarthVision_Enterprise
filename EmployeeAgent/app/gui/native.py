"""Hidden native window for Windows session and shutdown messages."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QWidget

from app.platform.windows import (
    ENDSESSION_LOGOFF,
    WM_ENDSESSION,
    WM_QUERYENDSESSION,
    WM_WTSSESSION_CHANGE,
    WindowsPlatform,
)

NOTIFY_FOR_THIS_SESSION = 0
HWND_MESSAGE = -3


class NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, owner: "NativeHooks") -> None:
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        try:
            if bytes(eventType).decode("utf-8", "ignore") not in {"windows_generic_MSG", "windows_dispatcher_MSG"}:
                return False, 0
        except Exception:
            return False, 0
        msg = ctypes.wintypes.MSG.from_address(int(message))
        self.owner.handle_msg(msg.message, msg.wParam, msg.lParam)
        return False, 0


class NativeHooks(QObject):
    sessionEvent = Signal(str)
    powerEvent = Signal(str)

    def __init__(self, platform: WindowsPlatform) -> None:
        super().__init__()
        self.platform = platform
        self._widget = QWidget()
        self._widget.setWindowTitle("EmployeeMonitoringAgentHidden")
        self._widget.resize(1, 1)
        self._widget.setVisible(False)
        self._filter = NativeFilter(self)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            app.installNativeEventFilter(self._filter)
        self._register_session(int(self._widget.winId()))

    def _register_session(self, hwnd: int) -> None:
        try:
            wts = ctypes.windll.wtsapi32  # type: ignore[attr-defined]
            wts.WTSRegisterSessionNotification(wintypes.HWND(hwnd), NOTIFY_FOR_THIS_SESSION)
        except Exception:
            pass

    def handle_msg(self, message: int, wparam: int, lparam: int) -> None:
        if message == WM_WTSSESSION_CHANGE:
            event = self.platform.handle_session_notification(int(wparam))
            if event:
                self.sessionEvent.emit(event)
        elif message in (WM_QUERYENDSESSION, WM_ENDSESSION):
            if int(lparam) & ENDSESSION_LOGOFF:
                event = self.platform.handle_end_session(int(lparam))
                self.sessionEvent.emit(event)
            else:
                event = self.platform.handle_end_session(int(lparam), restart=False)
                self.powerEvent.emit(event)
