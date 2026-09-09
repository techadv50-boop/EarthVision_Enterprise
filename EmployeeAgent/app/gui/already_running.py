from __future__ import annotations

import os
import sys

from app.constants import ALREADY_RUNNING_MESSAGE, APP_NAME


def show_already_running() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                ALREADY_RUNNING_MESSAGE,
                APP_NAME,
                0x40,
            )
            return
        except Exception:
            pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(None, APP_NAME, ALREADY_RUNNING_MESSAGE)
        if app.quitOnLastWindowClosed():
            pass
        return
    except Exception:
        print(ALREADY_RUNNING_MESSAGE, file=sys.stderr)
