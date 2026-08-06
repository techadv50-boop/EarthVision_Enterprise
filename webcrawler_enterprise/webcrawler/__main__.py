"""Application entry point."""

from __future__ import annotations

import sys


def main() -> int:
    from webcrawler.gui.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())