#!/usr/bin/env python3
"""Launch WebCrawler Enterprise (source or frozen standalone)."""

from __future__ import annotations

import sys


def _bootstrap() -> int:
    from webcrawler.runtime import (
        configure_runtime,
        show_fatal_error,
        windows_is_unsupported,
        write_crash_log,
    )

    configure_runtime()

    unsupported = windows_is_unsupported()
    if unsupported:
        show_fatal_error(unsupported)
        return 2

    from webcrawler.__main__ import main

    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(_bootstrap())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - must never fail silently in .exe
        try:
            from webcrawler.runtime import show_fatal_error, write_crash_log

            log_path = write_crash_log(exc)
            show_fatal_error(
                "WebCrawler Enterprise failed to start.\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                f"Details were saved to:\n{log_path}\n\n"
                "On Windows 10/11, also install Microsoft Visual C++ Redistributable:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                "Windows 7 is not supported."
            )
        except Exception:
            pass
        raise SystemExit(1)
