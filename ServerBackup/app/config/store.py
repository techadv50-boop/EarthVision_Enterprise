"""Load and save configuration. Secrets are never written except key *paths*."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from app.config.schema import AppConfig

APP_DIR_NAME = "ServerBackup"


def bundled_default_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "config" / "default.json"  # type: ignore[attr-defined]
    here = Path(__file__).resolve().parents[2]
    return here / "config" / "default.json"


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def default_config_path() -> Path:
    return config_dir() / "config.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def runtime_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".local" / "state" / APP_DIR_NAME


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON object in {path}")
    return data


def load_bundled_defaults() -> dict[str, Any]:
    path = bundled_default_path()
    if path.is_file():
        return _read_json(path)
    return AppConfig().to_dict()


def load_config(path: Path | None = None) -> AppConfig:
    merged = load_bundled_defaults()
    cfg_path = path or default_config_path()
    if cfg_path.is_file():
        merged.update(_read_json(cfg_path))
    return AppConfig.from_dict(merged)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    cfg_path = path or default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.to_dict()
    tmp = cfg_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    tmp.replace(cfg_path)
    return cfg_path


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    tmp.replace(path)
