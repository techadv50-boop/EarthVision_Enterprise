"""Keep N successful finalized backups. Incomplete/failed never count."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.utils.timeutil import parse_backup_id


def _info_status(directory: Path) -> str | None:
    info = directory / "backup-info.json"
    if not info.is_file():
        return None
    try:
        with info.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return str(data.get("status") or "")


def list_successful_backups(destination: str | Path) -> list[Path]:
    root = Path(destination)
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith("."):
            continue
        if name.startswith("incomplete") or name.startswith(".incomplete"):
            continue
        try:
            parse_backup_id(name)
        except ValueError:
            continue
        if _info_status(child) != "SUCCESS":
            continue
        found.append((name, child))
    found.sort(key=lambda item: item[0])
    return [path for _, path in found]


def list_history(destination: str | Path) -> list[dict[str, Any]]:
    root = Path(destination)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir() or child.name.startswith("."):
            continue
        info_path = child / "backup-info.json"
        record: dict[str, Any] = {
            "id": child.name,
            "location": str(child),
            "status": "UNKNOWN",
            "size": None,
            "duration": None,
            "sha256": None,
            "timestamp": child.name.replace("_", " "),
        }
        if info_path.is_file():
            try:
                with info_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    record.update(
                        {
                            "status": data.get("status") or record["status"],
                            "size": data.get("backup_size"),
                            "duration": data.get("duration_seconds"),
                            "sha256": data.get("sha256"),
                            "timestamp": data.get("timestamp") or record["timestamp"],
                            "info": data,
                        }
                    )
            except (OSError, json.JSONDecodeError):
                pass
        rows.append(record)
    return rows


def apply_retention(destination: str | Path, keep: int) -> list[Path]:
    """Delete oldest successful backups until `keep` remain.

    Must be called only after a new backup is finalized as SUCCESS.
    """
    keep = max(1, int(keep))
    successful = list_successful_backups(destination)
    removed: list[Path] = []
    extra = len(successful) - keep
    if extra <= 0:
        return removed
    for directory in successful[:extra]:
        shutil.rmtree(directory, ignore_errors=False)
        removed.append(directory)
    return removed
