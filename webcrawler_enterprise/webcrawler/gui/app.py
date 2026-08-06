"""PySide6 GUI application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog

from webcrawler import __app_name__
from webcrawler.auth.manager import AuthManager
from webcrawler.gui.login_dialog import LoginDialog
from webcrawler.gui.main_window import MainWindow


def run_app(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("WebCrawlerEnterprise")

    auth = AuthManager()
    login = LoginDialog(auth)
    if login.exec() != QDialog.Accepted or login.user is None:
        return 0

    window = MainWindow(auth=auth, user=login.user)
    window.show()
    return app.exec()
