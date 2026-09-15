"""On-demand three-layer security audit engine.

AUDIT → SNAPSHOT → COMPARE → CLASSIFY → REPORT
APPLY of host firewall/sshd is not performed automatically.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backup.lock import BackupLock
from app.config.schema import AppConfig
from app.logutil.logger import BackupLogger
from app.security.paths import validate_unix_path
from app.serversec.classify import classify_change, layer_status, overall_assessment
from app.serversec.credentials import mark_token_verified
from app.serversec.diff import compare_snapshots
from app.serversec.snapshot import SecurityStore
from app.ssh.client import SSHClient, SSHError


class SecurityError(RuntimeError):
    pass


class SecurityEngine:
    def __init__(self, config: AppConfig, *, ssh: SSHClient | None = None) -> None:
        self.config = config
        self.ssh = ssh or SSHClient(config)
        self.store = SecurityStore(config.security_store)
        self.logger = BackupLogger(config.log_directory)

    def _parse(self, stdout: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            raise SecurityError("Security audit returned no JSON.")
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        try:
            data, _end = decoder.raw_decode(text[text.find("{") :])
        except (json.JSONDecodeError, ValueError) as exc:
            raise SecurityError("Security audit returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise SecurityError("Security audit payload is not an object.")
        return data

    def _payload(self, action: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        validate_unix_path(self.config.remote_security_script, field="remote security script")
        data: dict[str, Any] = {
            "action": action,
            "mode": self.config.security_mode,
            "website_directories": self.config.website_directories,
            "ojs_private_files": self.config.ojs_private_files,
            "nginx_directory": self.config.nginx_directory,
            "extra_directories": self.config.extra_directories,
            "previous_mtime": None,
        }
        trusted = self.store.trusted_id()
        if trusted:
            try:
                prev = self.store.load_snapshot(trusted)
                data["previous_mtime"] = prev.get("collected_at_unix")
            except (OSError, ValueError):
                pass
        if extra:
            data.update(extra)
        return data

    def audit(self, *, accept_trusted: bool = False) -> dict[str, Any]:
        """On-demand check. Never scans continuously. Never stops production services."""
        lock = BackupLock(self.config.backup_destination)
        if lock.is_locked():
            raise SecurityError(
                "A backup is running. Security check was not started so production I/O is not increased."
            )
        snapshot_id = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        self.logger.info(f"Security check start {snapshot_id} mode={self.config.security_mode}")
        try:
            result = self.ssh.run_script(
                self.config.remote_security_script,
                self._payload("security-audit"),
                timeout=self.config.security_audit_timeout,
            )
        except SSHError as exc:
            self.logger.error(f"Security check failed: {exc}")
            raise SecurityError(str(exc)) from exc
        if not result.ok:
            raise SecurityError(result.stderr.strip() or result.stdout.strip() or "Security audit failed.")
        current = self._parse(result.stdout)
        current["id"] = snapshot_id
        current["collected_at"] = datetime.now().isoformat(timespec="seconds")
        current["security_mode"] = self.config.security_mode
        self.store.save_snapshot(current, snapshot_id)

        previous_id = self.store.trusted_id()
        findings: list[dict[str, Any]] = []
        if previous_id:
            try:
                previous = self.store.load_snapshot(previous_id)
                raw = compare_snapshots(previous, current)
                findings = [classify_change(item, previous={"id": previous_id}) for item in raw]
            except (OSError, ValueError) as exc:
                self.logger.warning(f"Could not compare with trusted snapshot: {exc}")
        else:
            findings.append(
                classify_change(
                    {
                        "kind": "modified",
                        "layer": "3",
                        "path": "",
                        "detail": "First snapshot; recorded as baseline without treating existing files as attacks.",
                    }
                )
            )
            findings[0]["severity"] = "EXPECTED/APPROPRIATE"
            findings[0]["reason"] = "No previous trusted snapshot existed. This audit is the baseline."

        # First-seen host issues even without a previous snapshot.
        findings.extend(_baseline_host_findings(current))
        seen: set[tuple] = set()
        unique: list[dict[str, Any]] = []
        for item in findings:
            key = (item.get("kind"), item.get("path"), item.get("detail"), item.get("severity"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        findings = unique

        report = {
            "id": snapshot_id,
            "timestamp": current["collected_at"],
            "security_mode": self.config.security_mode,
            "source_ip": self.config.server_ip,
            "hostname": current.get("hostname"),
            "server_health": (current.get("health") or {}).get("summary") or "UNKNOWN",
            "layer1": layer_status(findings, "1"),
            "layer2": layer_status(findings, "2"),
            "layer3": layer_status(findings, "3"),
            "examined": (current.get("integrity") or {}).get("examined") or len(current.get("files") or []),
            "findings": findings,
            "major_findings": [
                item
                for item in findings
                if item.get("severity") in {"REQUIRES REVIEW", "SUSPICIOUS", "CRITICAL"}
            ],
            "appropriate_changes": [
                item
                for item in findings
                if item.get("severity") in {"EXPECTED/APPROPRIATE", "LIKELY APPROPRIATE"}
            ],
            "previous_id": previous_id,
            "current_id": snapshot_id,
            "credential_rotation": "not performed",
            "enforcement": "audit-only; no production files were modified, quarantined, or deleted",
            "overall": overall_assessment(findings),
            "workflow": "AUDIT → SNAPSHOT → COMPARE → CLASSIFY → REPORT",
        }
        self.store.save_report(report, snapshot_id)
        if accept_trusted or previous_id is None:
            self.store.set_trusted(snapshot_id)
            mark_token_verified()
        self.logger.info(f"Security check complete overall={report['overall']}")
        self.logger.close()
        return report

    def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.store.load_snapshot(left_id)
        right = self.store.load_snapshot(right_id)
        findings = [classify_change(item) for item in compare_snapshots(left, right)]
        return {
            "left": left_id,
            "right": right_id,
            "label": f"{left_id} VS {right_id}",
            "findings": findings,
            "overall": overall_assessment(findings),
        }

    def rotate_remote_token(self, *, new_hash: str, confirmation: str) -> dict[str, Any]:
        if confirmation.strip() != "ROTATE":
            raise SecurityError("Credential rotation was not confirmed.")
        result = self.ssh.run_script(
            self.config.remote_security_script,
            self._payload(
                "security-rotate-token",
                {"token_hash": new_hash, "confirmation": "ROTATE"},
            ),
            timeout=60,
        )
        if not result.ok:
            raise SecurityError(result.stderr.strip() or "Remote token rotation failed; existing token left in place.")
        return self._parse(result.stdout)

    def rollback(self, rollback_id: str, *, confirmation: str) -> dict[str, Any]:
        if confirmation.strip() != "ROLLBACK":
            raise SecurityError("Type ROLLBACK to restore only application-managed security state.")
        from app.serversec.credentials import rollback_local_token

        local = rollback_local_token(self.store, rollback_id)
        result = self.ssh.run_script(
            self.config.remote_security_script,
            self._payload("security-rollback", {"rollback_id": rollback_id, "confirmation": "ROLLBACK"}),
            timeout=60,
        )
        remote: dict[str, Any] = {}
        if result.ok:
            try:
                remote = self._parse(result.stdout)
            except SecurityError:
                remote = {"ok": True, "message": "No remote app-managed security files to restore."}
        else:
            # Local rollback already applied; remote may not have the helper installed.
            remote = {"ok": False, "message": result.stderr.strip() or "Remote rollback skipped."}
        return {"local": local, "remote": remote}


def _baseline_host_findings(current: dict[str, Any]) -> list[dict[str, Any]]:
    extra: list[dict[str, Any]] = []
    layer1 = current.get("layer1") or {}
    sshd = layer1.get("sshd") or {}
    if str(sshd.get("PasswordAuthentication") or "").lower() in {"yes", "true"}:
        extra.append(
            classify_change(
                {
                    "kind": "ssh_password_auth_enabled",
                    "layer": "1",
                    "path": "/etc/ssh/sshd_config",
                    "detail": "PasswordAuthentication yes",
                }
            )
        )
    if str(sshd.get("PermitRootLogin") or "").lower() == "yes":
        extra.append(
            classify_change(
                {
                    "kind": "ssh_root_login",
                    "layer": "1",
                    "path": "/etc/ssh/sshd_config",
                    "detail": "PermitRootLogin yes",
                }
            )
        )
    if (current.get("layer2") or {}).get("sudo_unrestricted"):
        extra.append(
            classify_change(
                {
                    "kind": "sudo_unrestricted",
                    "layer": "2",
                    "path": "/etc/sudoers",
                    "detail": "NOPASSWD: ALL",
                }
            )
        )
    for svc in (current.get("health") or {}).get("services") or []:
        if isinstance(svc, dict) and svc.get("name") in {"nginx", "mariadb", "mysql", "ssh", "sshd"} and not svc.get("active"):
            extra.append(
                classify_change(
                    {
                        "kind": "service_inactive",
                        "layer": "2",
                        "service": svc.get("name"),
                        "detail": svc.get("name"),
                    }
                )
            )
    return extra
