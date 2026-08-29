"""Qt binding compatibility: PySide6 (Win10+) or PySide2 (Windows 7+)."""

from __future__ import annotations

QT_API = "none"

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QCloseEvent
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QStatusBar,
        QVBoxLayout,
        QWidget,
    )

    QT_API = "PySide6"
except Exception:  # ImportError or missing system libs (e.g. libEGL)
    try:
        from PySide2.QtCore import QObject, Qt, QTimer, Signal  # type: ignore
        from PySide2.QtGui import QCloseEvent  # type: ignore
        from PySide2.QtWidgets import (  # type: ignore
            QAction,
            QApplication,
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QSpinBox,
            QStatusBar,
            QVBoxLayout,
            QWidget,
        )

        QT_API = "PySide2"
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "WebCrawler Enterprise requires PySide6 (Windows 10+) "
            "or PySide2 (Windows 7+)."
        ) from exc


def qt_exec(obj):
    """Call exec()/exec_() across PySide2 and PySide6."""
    if hasattr(obj, "exec"):
        return obj.exec()
    return obj.exec_()
