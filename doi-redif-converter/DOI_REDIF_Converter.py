"""Entry point for the desktop application / PyInstaller builds."""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from pathlib import Path


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("DOI_REDIF_Converter.log")
    return Path(__file__).with_name("DOI_REDIF_Converter.log")


def _show_error(message: str) -> None:
    print(message, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("DOI → ReDIF Converter", message)
        root.destroy()
    except Exception:
        pass


def main() -> int:
    multiprocessing.freeze_support()
    log_file = _log_path()
    try:
        from app.desktop import main as desktop_main

        return desktop_main()
    except Exception:
        details = traceback.format_exc()
        try:
            log_file.write_text(details, encoding="utf-8")
        except Exception:
            pass
        _show_error(
            "The standalone program failed to start.\n\n"
            f"Details were saved to:\n{log_file}\n\n"
            f"{details[-1200:]}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
