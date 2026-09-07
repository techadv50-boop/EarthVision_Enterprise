#!/usr/bin/env python3
"""Server Backup entry point.

GUI (default):  python -m app.main
BACKUP NOW:     python -m app.main --backup
Scheduled:      python -m app.main --backup --mode scheduled

The GUI and Windows Task Scheduler call this same engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m app.main` from the ServerBackup directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import __app_name__, __version__  # noqa: E402
from app.backup.lock import BackupAlreadyRunning  # noqa: E402
from app.backup.progress import ProgressReporter  # noqa: E402
from app.config.store import default_config_path, load_config, save_config  # noqa: E402
from app.database.discover import discover_databases  # noqa: E402
from app.engine.backup_engine import BackupCancelled, BackupEngine, BackupError  # noqa: E402
from app.engine.status import progress_path  # noqa: E402
from app.ssh.client import SSHError  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{__app_name__} {__version__}")
    parser.add_argument("--gui", action="store_true", help="Open the dashboard (default)")
    parser.add_argument("--backup", action="store_true", help="Run a complete backup now")
    parser.add_argument("--dry-run", action="store_true", help="Check readiness without changing data")
    parser.add_argument("--test-connection", action="store_true")
    parser.add_argument("--discover-databases", action="store_true")
    parser.add_argument("--verify", metavar="ARCHIVE")
    parser.add_argument("--cancel", action="store_true", help="Request cancellation of a running backup")
    parser.add_argument("--mode", choices=["manual", "scheduled"], default="manual")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.json")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        print(f"{__app_name__} Version {__version__}")
        return 0
    config = load_config(args.config)
    if args.cancel:
        ProgressReporter(progress_path()).request_cancel()
        print("Cancel requested.")
        return 0
    if args.test_connection:
        engine = BackupEngine(config, mode=args.mode)
        result = engine.test_connection()
        print(json.dumps(result, indent=2))
        return 0 if result.get("login") else 2
    if args.discover_databases:
        rows = discover_databases(config)
        print(json.dumps(rows, indent=2))
        return 0
    if args.verify:
        from app.backup.checksum import sha256_file
        from app.backup.verify import verify_archive

        verify_archive(args.verify)
        print(sha256_file(args.verify))
        return 0
    if args.dry_run:
        engine = BackupEngine(config, mode=args.mode)
        result = engine.dry_run()
        print(json.dumps({k: v for k, v in result.items() if k != "remote"}, indent=2, default=str))
        return 0 if result.get("ok") else 3
    if args.backup:
        engine = BackupEngine(config, mode=args.mode)
        try:
            info = engine.run()
        except BackupAlreadyRunning as exc:
            print(str(exc))
            return 4
        except BackupCancelled as exc:
            print(str(exc))
            return 5
        except (BackupError, SSHError) as exc:
            print(str(exc))
            return 1
        print(f"BACKUP COMPLETED SUCCESSFULLY")
        print(f"ID: {info.get('backup_id')}")
        print(f"SHA-256: {info.get('sha256')}")
        return 0

    save_config(config, args.config or default_config_path())
    from app.gui.main_window import run_gui

    return run_gui(config)


if __name__ == "__main__":
    raise SystemExit(main())
