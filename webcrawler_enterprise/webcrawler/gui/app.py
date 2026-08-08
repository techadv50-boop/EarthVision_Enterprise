"""PySide6 GUI application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from webcrawler import __app_name__, __version__
from webcrawler.auth.manager import AuthManager
from webcrawler.gui.login_dialog import LoginDialog
from webcrawler.gui.main_window import MainWindow
from webcrawler.launch import prepare_launch_session


def run_app(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName(f"{__app_name__}")
    # Distinct from older builds so Qt does not share organization settings.
    app.setOrganizationName("WebCrawlerEnterprise_v2")
    app.setApplicationVersion(__version__)

    launch_info = prepare_launch_session()

    auth = AuthManager()
    if launch_info.get("legacy_present"):
        QMessageBox.information(
            None,
            f"{__app_name__} — isolated data store",
            "An older WebCrawler install was found on this PC, but this build\n"
            "does NOT use it.\n\n"
            f"New private folder:\n{launch_info.get('data_dir')}\n\n"
            f"Ignored old folder:\n{launch_info.get('legacy_dir')}\n\n"
            "Login for this build: admin / admin\n"
            "(you must change the password after login)\n\n"
            "Nothing will crawl until you click Start.\n"
            "Master reset code: NTZHSS",
        )

    login = LoginDialog(auth)
    if login.exec() != QDialog.Accepted or login.user is None:
        return 0

    window = MainWindow(auth=auth, user=login.user)
    window.show()
    return app.exec()
