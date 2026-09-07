"""Confirmed restore flows. Never overwrite production silently."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.backup.metadata import read_backup_info
from app.config.schema import AppConfig
from app.logutil.logger import BackupLogger
from app.security.paths import validate_unix_path
from app.ssh.client import SSHClient, SSHError

CONFIRMATION_PHRASE = "RESTORE"


class RestoreError(RuntimeError):
    pass


class RestoreEngine:
    def __init__(self, config: AppConfig, *, ssh: SSHClient | None = None) -> None:
        self.config = config
        self.ssh = ssh or SSHClient(config)
        self.logger = BackupLogger(config.log_directory)

    def _require_confirmation(self, confirmation: str) -> None:
        if confirmation.strip() != CONFIRMATION_PHRASE:
            raise RestoreError(
                f'Type {CONFIRMATION_PHRASE} to confirm. Restore was not started.'
            )

    def _payload(self, action: str, backup_dir: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        archive = backup_dir / "server-backup.tar.gz"
        if not archive.is_file():
            raise RestoreError(f"Backup archive not found: {archive}")
        info = {}
        try:
            info = read_backup_info(backup_dir)
        except (OSError, ValueError):
            info = {}
        if info.get("status") != "SUCCESS":
            raise RestoreError("Only successful backups can be restored.")
        data: dict[str, Any] = {
            "action": action,
            "create_safety_copy": True,
            "reload_nginx": False,
            "website_directories": self.config.website_directories,
            "ojs_private_files": self.config.ojs_private_files,
            "nginx_directory": self.config.nginx_directory,
            "databases": extra.get("databases") if extra else self.config.databases_for_backup(),
        }
        if extra:
            data.update(extra)
        return data

    def restore(
        self,
        backup_dir: str | Path,
        *,
        confirmation: str,
        action: str,
        target_path: str | None = None,
        database: str | None = None,
    ) -> dict[str, Any]:
        self._require_confirmation(confirmation)
        directory = Path(backup_dir)
        if action in {"restore-files", "restore-nginx"} and target_path:
            validate_unix_path(target_path, field="restore target")
        extra: dict[str, Any] = {}
        if target_path:
            extra["target_path"] = target_path
        if database:
            extra["databases"] = [database]
        payload = self._payload(action, directory, extra)
        self.logger.info(f"Restore requested action={action} backup={directory.name}")
        # The archive is on Windows. Push it via scp then invoke the restore script.
        archive = directory / "server-backup.tar.gz"
        remote_archive = f"/tmp/server-restore-{directory.name}.tar.gz"
        extra_payload = dict(payload)
        extra_payload["archive_path"] = remote_archive
        extra_payload["action"] = "restore-stage"
        # Upload then restore. Upload uses scp argv (no shell).
        self._upload(archive, remote_archive)
        extra_payload["action"] = action
        result = self.ssh.run_script(
            self.config.remote_restore_script,
            extra_payload,
            timeout=self.config.transfer_timeout,
        )
        if not result.ok:
            raise RestoreError(result.stderr.strip() or result.stdout.strip() or "Restore failed.")
        parsed: dict[str, Any] = {}
        text = result.stdout.strip()
        brace = text.rfind("{")
        if brace != -1:
            try:
                maybe = json.loads(text[brace:])
                if isinstance(maybe, dict):
                    parsed = maybe
            except json.JSONDecodeError:
                parsed = {}
        self.logger.info(f"Restore finished action={action}")
        self.logger.close()
        return parsed or {"ok": True, "message": result.stdout.strip()}

    def _upload(self, local: Path, remote: str) -> None:
        result = self.ssh.scp_upload(local, remote)
        if not result.ok:
            raise RestoreError(result.stderr.strip() or "Failed to upload backup archive for restore.")


def warning_text(kind: str) -> str:
    if kind == "restore-files":
        return (
            "WARNING: Restoring website files may overwrite live production files.\n\n"
            "A safety copy of the current remote files will be created where practical.\n"
            "This will not start automatically. Type RESTORE to confirm."
        )
    if kind == "restore-database":
        return (
            "WARNING: This operation may overwrite the existing database.\n\n"
            "A current database safety dump will be created where practical.\n"
            "Websites that use this database may serve old or inconsistent data until you verify them.\n"
            "Type RESTORE to confirm."
        )
    if kind == "restore-nginx":
        return (
            "WARNING: Restoring /etc/nginx/ may change how every site is served.\n\n"
            "A safety copy of the current Nginx configuration will be created.\n"
            "Nginx configuration will be validated with nginx -t.\n"
            "Nginx will NOT be restarted automatically.\n"
            "Type RESTORE to confirm."
        )
    return (
        "WARNING: A complete restore may overwrite website files, databases, and Nginx configuration.\n\n"
        "Safety copies will be created where practical. Nginx will not be restarted automatically.\n"
        "Type RESTORE to confirm."
    )
