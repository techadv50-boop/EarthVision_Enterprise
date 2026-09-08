"""Run read-only application discovery over the existing SSH helper."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config.schema import AppConfig
from app.discover.policy import apply_policy, save_snapshot
from app.discover.report import format_discovery_report
from app.ssh.client import SSHClient, SSHError


class DiscoveryError(RuntimeError):
    pass


def discover_applications(
    config: AppConfig,
    *,
    ssh: SSHClient | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    client = ssh or SSHClient(config)
    try:
        login = client.test_login()
        if not login.ok:
            raise DiscoveryError(login.stderr.strip() or "SSH login failed.")
        helpers = client.ensure_remote_scripts()
        if not helpers.ok:
            raise DiscoveryError(helpers.stderr.strip() or "Could not install Ubuntu backup helpers.")
        result = client.run_script(
            config.remote_prepare_script,
            {"action": "discover-applications"},
            timeout=120,
        )
        parsed = _parse_json(result.stdout)
        if not result.ok and not parsed:
            raise DiscoveryError(result.stderr.strip() or result.stdout.strip() or "Application discovery failed.")
        if parsed.get("ok") is False and not parsed.get("applications"):
            raise DiscoveryError(str(parsed.get("error") or result.stderr.strip() or "Application discovery failed."))
        apps = apply_policy(list(parsed.get("applications") or []), config.backup_destination)
        parsed["applications"] = apps
        parsed["report_text"] = format_discovery_report(parsed)
        parsed["discovered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if persist:
            save_snapshot(
                config.backup_destination,
                {
                    "discovered_at": parsed["discovered_at"],
                    "applications": [
                        {
                            "application_id": item.get("application_id"),
                            "hostname": item.get("hostname"),
                            "hostnames": list(item.get("hostnames") or [item.get("hostname")]),
                            "hostname_details": item.get("hostname_details") or {},
                            "type": item.get("type"),
                            "root": item.get("root"),
                            "status": item.get("status"),
                            "database_type": item.get("database_type"),
                            "database_name": item.get("database_name"),
                            "source_file": item.get("source_file"),
                            "alias": list(item.get("alias") or []),
                            "proxy_pass": list(item.get("proxy_pass") or []),
                            "redirect_to": item.get("redirect_to") or "",
                        }
                        for item in apps
                        if item.get("change") != "removed"
                    ],
                },
            )
        return parsed
    finally:
        closer = getattr(client, "close", None)
        if callable(closer) and ssh is None:
            closer()


def _parse_json(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        return {}
    import json

    decoder = json.JSONDecoder()
    brace = text.find("{")
    while brace != -1:
        try:
            data, _end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            brace = text.find("{", brace + 1)
            continue
        if isinstance(data, dict) and ("applications" in data or "ok" in data):
            return data
        brace = text.find("{", brace + 1)
    return {}
