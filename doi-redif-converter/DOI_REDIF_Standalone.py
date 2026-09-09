"""Standalone entry point — native desktop GUI only (no browser, no web server)."""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from pathlib import Path

APP_VERSION = "1.3.0"
APP_TITLE = f"DOI/URL → ReDIF Standalone v{APP_VERSION}"


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("DOI_REDIF_Standalone.log")
    return Path(__file__).with_name("DOI_REDIF_Standalone.log")


def _show_error(message: str) -> None:
    print(message, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message)
        root.destroy()
    except Exception:
        input("Press Enter to close…")


def main() -> int:
    multiprocessing.freeze_support()
    log_file = _log_path()
    print(APP_TITLE)
    print("Starting native desktop window (NOT a browser)…")
    try:
        # Import GUI directly — never start uvicorn/FastAPI/web UI
        from app import gui

        gui.APP_TITLE = APP_TITLE
        return gui.run_app()
    except Exception:
        details = traceback.format_exc()
        try:
            log_file.write_text(details, encoding="utf-8")
        except Exception:
            pass
        _show_error(
            "The standalone program failed to start.\n\n"
            f"Log file:\n{log_file}\n\n"
            f"{details[-1500:]}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
