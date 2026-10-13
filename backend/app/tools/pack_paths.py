"""Configurable Tool Pack filesystem roots (Docker-safe).

Production/preview containers should set:

- ``EV_RUNTIME_PINS`` → absolute path to ``runtime_pins.json`` on the tool_packs volume
- ``EV_ARTIFACTS_ROOT`` → absolute path to the artifacts directory on that volume

When unset (local repo checkout), paths fall back to ``<repo>/tools/...``.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Best-effort monorepo root (backend/app/tools → parents[3]).

    Inside the backend image (``COPY backend/ .`` → ``/app``), parents[3] is ``/``
    and is **not** used when ``EV_*`` overrides are set — which is required in Docker.
    """
    return Path(__file__).resolve().parents[3]


def pins_path() -> Path:
    override = os.environ.get("EV_RUNTIME_PINS")
    if override:
        return Path(override)
    return repo_root() / "tools" / "runtime_pins.json"


def artifacts_root() -> Path:
    override = os.environ.get("EV_ARTIFACTS_ROOT")
    if override:
        return Path(override)
    return repo_root() / "tools" / "artifacts"


def tool_packs_root() -> Path:
    """Parent directory for pins, artifacts, staging, and audit (when using volume layout)."""
    override = os.environ.get("EV_TOOL_PACKS_ROOT")
    if override:
        return Path(override)
    # Derive from pins path when possible
    pins = pins_path()
    if pins.name == "runtime_pins.json":
        return pins.parent
    return artifacts_root().parent


def staging_root() -> Path:
    return tool_packs_root() / "staging"


def audit_log_path() -> Path:
    override = os.environ.get("EV_PACK_AUDIT_LOG")
    if override:
        return Path(override)
    return tool_packs_root() / "audit" / "promotions.jsonl"


def publishers_path() -> Path:
    override = os.environ.get("EV_PACK_PUBLISHERS")
    if override:
        return Path(override)
    # Prefer volume copy, else repo allowlist
    vol = tool_packs_root() / "publishers" / "approved_publishers.json"
    if vol.is_file():
        return vol
    return repo_root() / "tools" / "publishers" / "approved_publishers.json"


def pack_dir(tool_id: str, version: str) -> Path:
    return artifacts_root() / tool_id / version
