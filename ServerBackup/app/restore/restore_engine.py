"""Confirmed restore flows. Never overwrite production silently."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.backup.metadata import read_backup_info
from app.config.schema import AppConfig
from app.logutil.logger import BackupLogger
from app.master.restore import select_tree_files, write_database_pack, write_restore_pack
from app.master.store import MasterStore
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
        generation: int | None = None,
    ) -> dict[str, Any]:
        self._require_confirmation(confirmation)
        token = str(backup_dir)
        if token.startswith("master:"):
            gen = generation
            if gen is None:
                try:
                    gen = int(token.split(":", 1)[1])
                except ValueError as exc:
                    raise RestoreError("Invalid master generation.") from exc
            return self.restore_master(
                confirmation=confirmation,
                action=action,
                generation=gen,
                target_path=target_path,
                database=database,
            )
        directory = Path(backup_dir)
        if directory.name == "master" or (directory / "HEAD").is_file():
            return self.restore_master(
                confirmation=confirmation,
                action=action,
                generation=generation,
                target_path=target_path,
                database=database,
            )
        if action in {"restore-files", "restore-nginx"} and target_path:
            validate_unix_path(target_path, field="restore target")
        extra: dict[str, Any] = {}
        if target_path:
            extra["target_path"] = target_path
        if database:
            extra["databases"] = [database]
        payload = self._payload(action, directory, extra)
        self.logger.info(f"Restore requested action={action} backup={directory.name}")
        archive = directory / "server-backup.tar.gz"
        remote_archive = f"/tmp/server-restore-{directory.name}.tar.gz"
        extra_payload = dict(payload)
        extra_payload["archive_path"] = remote_archive
        extra_payload["action"] = action
        self._upload(archive, remote_archive)
        result = self.ssh.run_script(
            self.config.remote_restore_script,
            extra_payload,
            timeout=self.config.transfer_timeout,
        )
        if not result.ok:
            raise RestoreError(result.stderr.strip() or result.stdout.strip() or "Restore failed.")
        parsed = _parse_json(result.stdout)
        self.logger.info(f"Restore finished action={action}")
        self.logger.close()
        return parsed or {"ok": True, "message": result.stdout.strip()}

    def restore_master(
        self,
        *,
        confirmation: str,
        action: str,
        generation: int | None = None,
        target_path: str | None = None,
        database: str | None = None,
    ) -> dict[str, Any]:
        self._require_confirmation(confirmation)
        if action in {"restore-files", "restore-nginx"} and target_path:
            validate_unix_path(target_path, field="restore target")
        store = MasterStore(self.config.backup_destination)
        if not store.has_head():
            raise RestoreError(
                "No master HEAD exists. Restore from a 1.3.7 archive instead, or run BACKUP NOW first."
            )
        gen = store.head_generation() if generation is None else int(generation)
        tree = store.load_tree(gen)
        pack_dir = store.begin_staging(f"restore{gen}")
        pack_path = pack_dir / "restore.sb01"
        names = [database] if database else list(tree.get("databases") or self.config.databases_for_backup())
        try:
            if action == "restore-database":
                if not names or not names[0]:
                    raise RestoreError("Select a database to restore.")
                write_database_pack(store, tree, [n for n in names if n], pack_path)
            elif action == "restore-complete":
                records = select_tree_files(tree, kind=action, target_path=None)
                write_restore_pack(store, records, pack_path)
                if names:
                    self._append_database_objects(store, tree, [n for n in names if n], pack_path)
            else:
                records = select_tree_files(tree, kind=action, target_path=target_path)
                if not records:
                    raise RestoreError("No files in this master generation match the restore type.")
                write_restore_pack(store, records, pack_path)
            remote_pack = f"/tmp/server-restore-master-{gen}.sb01"
            self._upload(pack_path, remote_pack)
            payload = {
                "action": "restore-master",
                "pack_path": remote_pack,
                "create_safety_copy": True,
                "reload_nginx": False,
            }
            self.logger.info(f"Master restore generation={gen} action={action}")
            result = self.ssh.run_script(
                self.config.remote_restore_script,
                payload,
                timeout=self.config.transfer_timeout,
            )
            if not result.ok:
                raise RestoreError(result.stderr.strip() or result.stdout.strip() or "Master restore failed.")
            parsed = _parse_json(result.stdout)
            parsed.setdefault("nginx_restarted", False)
            return parsed or {"ok": True, "message": result.stdout.strip(), "nginx_restarted": False}
        finally:
            store.cleanup_staging(f"restore{gen}")
            closer = getattr(self.ssh, "close", None)
            if callable(closer):
                closer()
            self.logger.close()

    def _append_database_objects(
        self, store: MasterStore, tree: dict[str, Any], names: list[str], pack_path: Path
    ) -> None:
        extra = pack_path.with_suffix(".db")
        write_database_pack(store, tree, names, extra)
        data = pack_path.read_bytes()
        extra_bytes = extra.read_bytes()
        if data.endswith(b"\x00\x00\x00\x00"):
            pack_path.write_bytes(data[:-4] + extra_bytes[4:])
        extra.unlink(missing_ok=True)

    def _upload(self, local: Path, remote: str) -> None:
        result = self.ssh.scp_upload(local, remote)
        if not result.ok:
            raise RestoreError(result.stderr.strip() or "Failed to upload backup archive for restore.")


def _parse_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    brace = text.rfind("{")
    if brace == -1:
        return {}
    try:
        maybe = json.loads(text[brace:])
    except json.JSONDecodeError:
        return {}
    return maybe if isinstance(maybe, dict) else {}


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
