"""backup-info.json writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_backup_info(directory: str | Path, info: dict[str, Any]) -> Path:
    path = Path(directory) / "backup-info.json"
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(info, handle, indent=2)
        handle.write("\n")
    tmp.replace(path)
    return path


def read_backup_info(directory: str | Path) -> dict[str, Any]:
    path = Path(directory) / "backup-info.json"
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("backup-info.json is not an object")
    return data
