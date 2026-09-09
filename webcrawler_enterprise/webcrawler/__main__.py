"""Application entry point."""

from __future__ import annotations

import sys


def main() -> int:
    # Runtime/env is configured by main.py before this is called in frozen builds.
    from webcrawler.gui.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    from webcrawler.runtime import configure_runtime

    configure_runtime()
    raise SystemExit(main())
