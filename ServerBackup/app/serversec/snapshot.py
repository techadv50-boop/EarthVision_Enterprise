"""Local security snapshot store. Does not copy production website files."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from app.utils.timeutil import backup_id_now


class SecurityStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.reports = self.root / "reports"
        self.rollback = self.root / "rollback"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        self.rollback.mkdir(parents=True, exist_ok=True)

    def _pointer_path(self) -> Path:
        return self.root / "trusted.json"

    def list_snapshots(self) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for path in sorted(self.snapshots.glob("*.json.gz"), reverse=True):
            name = path.name[: -len(".json.gz")]
            cleaned.append({"id": name, "path": str(path), "name": name})
        return cleaned

    def save_snapshot(self, payload: dict[str, Any], snapshot_id: str | None = None) -> str:
        sid = snapshot_id or backup_id_now()
        payload = dict(payload)
        payload["id"] = sid
        path = self.snapshots / f"{sid}.json.gz"
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        tmp.replace(path)
        return sid

    def load_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        path = self.snapshots / f"{snapshot_id}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Invalid snapshot")
        return data

    def save_report(self, report: dict[str, Any], snapshot_id: str) -> Path:
        path = self.reports / f"security-{snapshot_id}.json"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        tmp.replace(path)
        text = self.reports / f"security-{snapshot_id}.txt"
        text.write_text(_report_text(report), encoding="utf-8")
        return path

    def load_report(self, snapshot_id: str) -> dict[str, Any]:
        path = self.reports / f"security-{snapshot_id}.json"
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Invalid report")
        return data

    def trusted_id(self) -> str | None:
        pointer = self._pointer_path()
        if not pointer.is_file():
            return None
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return str(data.get("id") or "") or None

    def set_trusted(self, snapshot_id: str) -> None:
        pointer = self._pointer_path()
        tmp = pointer.with_suffix(".tmp")
        tmp.write_text(json.dumps({"id": snapshot_id}, indent=2) + "\n", encoding="utf-8")
        tmp.replace(pointer)

    def save_rollback_point(self, payload: dict[str, Any]) -> Path:
        path = self.rollback / f"{payload.get('id') or backup_id_now()}.json"
        # Never persist plaintext credentials.
        safe = {k: v for k, v in payload.items() if k not in {"old_token", "new_token", "password", "secret"}}
        path.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
        return path

    def list_rollback_points(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.rollback.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"id": path.stem}
            data["path"] = str(path)
            rows.append(data)
        return rows

    def latest_id(self) -> str | None:
        items = self.list_snapshots()
        return items[0]["id"] if items else None


def _report_text(report: dict[str, Any]) -> str:
    lines = [
        f"Server Security Report {report.get('id')}",
        f"Mode: {report.get('security_mode')}",
        f"Overall: {report.get('overall')}",
        f"Server health: {report.get('server_health')}",
        "",
        "Layer status:",
        f"  1 Entry: {report.get('layer1')}",
        f"  2 Access: {report.get('layer2')}",
        f"  3 Integrity: {report.get('layer3')}",
        "",
        f"Files/folders examined: {report.get('examined')}",
        f"Previous snapshot: {report.get('previous_id') or 'none (baseline)'}",
        "",
        "Major findings:",
    ]
    for item in report.get("findings") or []:
        if item.get("severity") in {"REQUIRES REVIEW", "SUSPICIOUS", "CRITICAL"}:
            lines.append(
                f"- [{item.get('severity')}] {item.get('kind')} {item.get('path') or ''} — {item.get('reason')}"
            )
    lines.append("")
    lines.append("Appropriate / likely appropriate:")
    for item in report.get("findings") or []:
        if item.get("severity") in {"EXPECTED/APPROPRIATE", "LIKELY APPROPRIATE"}:
            lines.append(f"- [{item.get('severity')}] {item.get('kind')} {item.get('path') or ''}")
    if report.get("credential_rotation"):
        lines.append("")
        lines.append(f"Credential rotation: {report.get('credential_rotation')}")
    lines.append("")
    lines.append("No passwords, private keys, or recovered secrets are included in this report.")
    return "\n".join(lines) + "\n"
