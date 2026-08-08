"""PySide6 GUI application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from webcrawler import __app_name__
from webcrawler.auth.manager import AuthManager
from webcrawler.gui.login_dialog import LoginDialog
from webcrawler.gui.main_window import MainWindow
from webcrawler.launch import prepare_launch_session


def run_app(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("WebCrawlerEnterprise")

    # New builds must not inherit old password session / URL list / auto-run queue.
    launch_info = prepare_launch_session()

    auth = AuthManager()
    if launch_info.get("migrated"):
        QMessageBox.information(
            None,
            f"{__app_name__} — clean start",
            "This PC still had data from an older run.\n\n"
            "For this new build:\n"
            "• Login reset to: admin / admin\n"
            "• You must change the password after login\n"
            "• Old URLs were cleared\n"
            "• Nothing will crawl until you click Start\n\n"
            "Master reset code (if needed later): NTZHSS",
        )

    login = LoginDialog(auth)
    if login.exec() != QDialog.Accepted or login.user is None:
        return 0

    window = MainWindow(auth=auth, user=login.user)
    window.show()
    return app.exec()
