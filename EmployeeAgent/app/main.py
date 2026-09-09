#!/usr/bin/env python3
"""Employee Monitoring Agent entry point.

GUI/tray (default):  python -m app.main
Background:          python -m app.main --background
Admin status:        python -m app.main --status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import __app_name__, __version__  # noqa: E402
from app.config.paths import resolve_paths  # noqa: E402
from app.config.store import ConfigStore  # noqa: E402
from app.constants import ALREADY_RUNNING_MESSAGE  # noqa: E402
from app.platform import create_platform  # noqa: E402
from app.runtime.instance import SingleInstanceLock  # noqa: E402
from app.runtime.logging import setup_logging  # noqa: E402
from app.runtime.status_file import StatusFile  # noqa: E402
from app.service.agent import AgentService  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{__app_name__} {__version__}")
    parser.add_argument("--background", action="store_true", help="Start in the tray with no dashboard window")
    parser.add_argument("--headless", action="store_true", help="Run monitoring without a GUI (tests / service)")
    parser.add_argument("--status", action="store_true", help="Print whether the agent is running")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser


def print_status(paths) -> int:
    status = StatusFile(paths.status_file)
    data = status.read()
    if not data:
        print(json.dumps({"running": False, "reason": "no_status_file"}))
        return 3
    pid = int(data.get("pid") or 0)
    running = bool(data.get("running")) and status.is_process_running(pid)
    data["running"] = running
    print(json.dumps(data, indent=2))
    return 0 if running else 3


def show_already_running() -> None:
    try:
        from app.gui.already_running import show_already_running as _show

        _show()
    except Exception:
        print(ALREADY_RUNNING_MESSAGE, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        print(f"{__app_name__} {__version__}")
        return 0
    paths = resolve_paths(args.data_dir)
    paths.ensure()
    logger = setup_logging(paths.log_file)
    if args.status:
        return print_status(paths)

    lock = SingleInstanceLock(paths.lock_file, paths.mutex_name)
    if not lock.acquire():
        show_already_running()
        return 1
    service = None
    try:
        config = ConfigStore(paths.config_file).load()
        platform = create_platform()
        if not config.device_id:
            config.device_id = platform.hostname()
        service = AgentService(paths, config, platform)
        try:
            service.start_background()
        except Exception:
            logger.exception("Agent startup failed")
            raise
        if args.headless:
            try:
                while service.is_monitoring():
                    service._stop.wait(1.0)  # noqa: SLF001
            except KeyboardInterrupt:
                pass
            return 0
        try:
            from app.gui.app import AgentGui
        except ImportError:
            logger.error("PySide6 is required for the desktop UI. pip install PySide6")
            return 2
        gui = AgentGui(service, background=args.background)
        return gui.run()
    finally:
        if service is not None and service.is_monitoring():
            service.stop(record_exit=False)
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
