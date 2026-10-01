"""Desktop entry: launch the standalone tkinter app (no browser)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


APP_TITLE = "DOI / URL → ReDIF Converter"


def _log_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("DOI_REDIF_Converter.log")
    return Path(__file__).resolve().parent.parent / "DOI_REDIF_Converter.log"


def main() -> int:
    try:
        from app.gui import run_app

        print(f"{APP_TITLE}")
        print("Opening standalone desktop window…")
        return run_app()
    except Exception:
        details = traceback.format_exc()
        log = _log_file()
        try:
            log.write_text(details, encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                APP_TITLE,
                "The program failed to start.\n\n"
                f"Log file:\n{log}\n\n{details[-1200:]}",
            )
            root.destroy()
        except Exception:
            print(details, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
