"""PySide6 GUI application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from webcrawler import __app_name__
from webcrawler.gui.main_window import MainWindow


def run_app(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("WebCrawlerEnterprise")
    window = MainWindow()
    window.show()
    return app.exec()
