"""Discover MariaDB databases over SSH. Names are never hardcoded."""

from __future__ import annotations

import json

from app.config.schema import AppConfig, SYSTEM_DATABASES
from app.ssh.client import SSHClient, SSHError


def discover_databases(config: AppConfig, client: SSHClient | None = None) -> list[dict[str, object]]:
    ssh = client or SSHClient(config)
    payload = {"action": "discover-databases"}
    result = ssh.run_script(config.remote_prepare_script, payload, timeout=60)
    if not result.ok:
        raise SSHError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Database discovery failed. Confirm the Ubuntu setup script has been run."
        )
    text = result.stdout.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SSHError("Database discovery returned invalid JSON.") from exc
    names = data.get("databases") if isinstance(data, dict) else data
    if not isinstance(names, list):
        raise SSHError("Database discovery returned an unexpected payload.")
    rows: list[dict[str, object]] = []
    for raw in names:
        name = str(raw)
        rows.append(
            {
                "name": name,
                "system": name in SYSTEM_DATABASES,
                "selected": name in config.selected_databases
                or (name not in SYSTEM_DATABASES and not config.selected_databases),
            }
        )
    return rows
