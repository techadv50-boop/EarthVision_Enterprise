"""Runtime path helpers and fatal-error reporting for frozen builds."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def app_base_dir() -> Path:
    """Directory containing the executable (frozen) or project root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def configure_runtime() -> Path:
    """
    Configure environment for standalone Windows packages.

    Points Playwright at a locally bundled ms-playwright folder when present
    so end users do not need Python, VS Code, or `playwright install`.
    """
    base = app_base_dir()
    # Prefer browsers next to the exe; also support _internal layout leftovers
    for candidate in (base / "ms-playwright", base / "_internal" / "ms-playwright"):
        if candidate.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            break
    os.environ.setdefault("PYTHONUTF8", "1")
    # Helps some Qt plugin lookups in frozen builds
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        for qt_name in ("PySide2", "PySide6"):
            plugin = base / "_internal" / qt_name / "plugins"
            if plugin.is_dir():
                os.environ.setdefault("QT_PLUGIN_PATH", str(plugin))
            if meipass:
                meipass_plugin = Path(meipass) / qt_name / "plugins"
                if meipass_plugin.is_dir():
                    os.environ["QT_PLUGIN_PATH"] = str(meipass_plugin)
    return base


def _qt_api() -> str:
    try:
        from webcrawler.qtcompat import QT_API

        return QT_API
    except Exception:
        return "PySide6"


def windows_is_unsupported() -> str | None:
    """Return a user message if the OS cannot run this build."""
    if sys.platform != "win32":
        return None
    try:
        version = sys.getwindowsversion()
    except Exception:
        return None

    # Windows 7 = 6.1, Windows 8 = 6.2/6.3, Windows 10/11 = 10.0
    is_win7_or_newer = version.major > 6 or (
        version.major == 6 and version.minor >= 1
    )
    if not is_win7_or_newer:
        return (
            "This application requires Windows 7 SP1 (64-bit) or newer.\n\n"
            f"Detected Windows version: {version.major}.{version.minor}"
        )

    # PySide2 / Win7 build: allow Windows 7 and 8.
    if _qt_api() == "PySide2":
        return None

    # PySide6 / modern build: Windows 10+
    if version.major < 10:
        return (
            "This standalone build requires Windows 10 or Windows 11 (64-bit).\n\n"
            f"Detected Windows version: {version.major}.{version.minor}\n\n"
            "Please download the Windows 7 compatible package:\n"
            "WebCrawlerEnterprise-Standalone-Windows7"
        )
    return None


def write_crash_log(exc: BaseException) -> Path:
    base = app_base_dir()
    path = base / "crash_log.txt"
    text = [
        "WebCrawler Enterprise crash log",
        f"Time (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Executable: {sys.executable}",
        f"Frozen: {getattr(sys, 'frozen', False)}",
        f"Python: {sys.version}",
        f"Platform: {sys.platform}",
        f"Qt API: {_qt_api()}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    path.write_text("\n".join(text), encoding="utf-8")
    return path


def show_fatal_error(message: str) -> None:
    """Show an error dialog when possible; always print to stderr."""
    print(message, file=sys.stderr)
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "WebCrawler Enterprise", 0x10)
            return
    except Exception:
        pass
    try:
        from webcrawler.qtcompat import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "WebCrawler Enterprise", message)
    except Exception:
        pass
