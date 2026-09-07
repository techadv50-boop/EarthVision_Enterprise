"""Single backup engine used by BACKUP NOW and Task Scheduler.

This module never stops Nginx, PHP-FPM, or MariaDB and never mutates
production website files or databases. Restore is a separate confirmed flow.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app import __version__
from app.backup.checksum import sha256_file
from app.backup.lock import BackupAlreadyRunning, BackupLock
from app.backup.metadata import write_backup_info
from app.backup.progress import ProgressReporter
from app.backup.retention import apply_retention
from app.backup.transfer import TransferCancelled, stream_copy
from app.backup.verify import ArchiveIntegrityError, verify_archive
from app.config.schema import AppConfig
from app.config.store import runtime_dir, save_state
from app.logutil.logger import BackupLogger, prune_logs
from app.security.paths import PathValidationError, validate_unix_path
from app.ssh.client import SSHClient, SSHError
from app.utils.disk import drive_status, ensure_directory
from app.utils.timeutil import backup_id_now


class BackupError(RuntimeError):
    pass


class BackupCancelled(BackupError):
    def __init__(self, message: str = "Backup cancelled.") -> None:
        super().__init__(message)


class BackupEngine:
    def __init__(
        self,
        config: AppConfig,
        *,
        ssh: SSHClient | None = None,
        progress: ProgressReporter | None = None,
        logger: BackupLogger | None = None,
        mode: str = "manual",
    ) -> None:
        self.config = config
        self.ssh = ssh or SSHClient(config)
        self.mode = mode
        self.backup_id = backup_id_now()
        self.logger = logger or BackupLogger(config.log_directory, self.backup_id.split("_")[0])
        self.progress = progress or ProgressReporter(runtime_dir() / "progress.json")
        self.lock = BackupLock(config.backup_destination)
        self.incomplete_dir: Path | None = None
        self.final_dir: Path | None = None
        self._started = datetime.now()
        self._remote_work_id: str | None = None
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.transfer_fn: Callable[[Path], int] | None = None

    def _check_cancel(self) -> None:
        if self.progress.cancel_requested():
            raise BackupCancelled("Backup cancelled.")

    def _retry(self, label: str, func: Callable[[], Any]) -> Any:
        attempts = max(1, int(self.config.retry_count))
        delay = max(1, int(self.config.retry_delay_seconds))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._check_cancel()
            try:
                self.logger.info(f"{label}: attempt {attempt}/{attempts}")
                return func()
            except BackupCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — retry temporary network/SSH errors
                last_error = exc
                self.logger.warning(f"{label} failed on attempt {attempt}: {exc}")
                if attempt < attempts:
                    self.progress.write(
                        message=f"{label} failed, retrying in {delay}s (attempt {attempt}/{attempts})"
                    )
                    time.sleep(delay)
        assert last_error is not None
        raise last_error

    def _validate_config_paths(self) -> None:
        for directory in self.config.website_directories:
            validate_unix_path(directory, field="website directory")
        validate_unix_path(self.config.ojs_private_files, field="OJS private-files directory")
        validate_unix_path(self.config.nginx_directory, field="Nginx directory")
        for directory in self.config.extra_directories:
            validate_unix_path(directory, field="additional directory")
        validate_unix_path(self.config.remote_prepare_script, field="remote prepare script")

    def _cleanup_incomplete(self) -> None:
        if self.incomplete_dir and self.incomplete_dir.exists():
            shutil.rmtree(self.incomplete_dir, ignore_errors=True)
            self.logger.info(f"Removed incomplete backup {self.incomplete_dir}")
        if self._remote_work_id:
            try:
                self.ssh.run_script(
                    self.config.remote_prepare_script,
                    {"action": "cleanup", "work_id": self._remote_work_id},
                    timeout=120,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"Remote cleanup warning: {exc}")

    def _payload(self, action: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": action,
            "work_id": self.backup_id.replace("_", ""),
            "website_directories": self.config.website_directories,
            "ojs_private_files": self.config.ojs_private_files,
            "nginx_directory": self.config.nginx_directory,
            "extra_directories": self.config.extra_directories,
            "databases": self.config.databases_for_backup(),
            "compression_level": self.config.compression_level,
            "min_free_disk_gb": self.config.min_remote_free_disk_gb,
        }
        if extra:
            data.update(extra)
        return data

    def _parse_json_result(self, stdout: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            return {}
        # The remote script may print logs; take the last JSON object.
        last_brace = text.rfind("{")
        if last_brace == -1:
            return {}
        try:
            data = json.loads(text[last_brace:])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def test_connection(self) -> dict[str, Any]:
        results: dict[str, Any] = {
            "reachable": False,
            "ssh_port": False,
            "ssh_key": False,
            "login": False,
            "permissions": False,
            "script": False,
            "details": [],
        }
        self.logger.info("Testing connection to Ubuntu server")
        try:
            login = self.ssh.test_login()
            results["reachable"] = True
            results["ssh_port"] = True
            results["ssh_key"] = login.ok
            results["login"] = login.ok
            results["details"].append("SSH login: OK" if login.ok else f"SSH login failed: {login.stderr}")
            if not login.ok:
                return results
            check = self.ssh.run_script(
                self.config.remote_prepare_script,
                self._payload("check"),
                timeout=60,
            )
            results["script"] = check.ok
            results["permissions"] = check.ok
            parsed = self._parse_json_result(check.stdout)
            results["check"] = parsed
            if check.ok:
                results["details"].append("Backup script: OK")
            else:
                results["details"].append(
                    check.stderr.strip()
                    or "Backup script could not be executed. Run ubuntu-backup-setup.sh on the server."
                )
        except SSHError as exc:
            results["details"].append(str(exc))
            self.logger.error(f"Connection test failed: {exc}")
        return results

    def dry_run(self) -> dict[str, Any]:
        self.progress.write(status="running", phase="dry-run", backup_id=self.backup_id, message="Dry run…")
        report: dict[str, Any] = {"ok": False, "checks": []}

        def note(name: str, ok: bool, detail: str = "") -> None:
            report["checks"].append({"name": name, "ok": ok, "detail": detail})
            self.progress.add_step(name, ok, detail)

        drive = drive_status(self.config.backup_destination)
        note("G: / backup drive", drive.exists, drive.error or f"{drive.free_gb:.1f} GB free")
        if drive.exists:
            enough = drive.free_gb >= self.config.min_free_disk_gb
            note("Windows free space", enough, f"{drive.free_gb:.1f} GB free")
        try:
            self._validate_config_paths()
            note("Configuration paths", True)
        except PathValidationError as exc:
            note("Configuration paths", False, str(exc))
            report["ok"] = False
            self.progress.write(status="failed", error=str(exc))
            return report
        try:
            login = self.ssh.test_login()
            note("SSH", login.ok, login.stderr.strip() if not login.ok else "OK")
        except SSHError as exc:
            note("SSH", False, str(exc))
            self.progress.write(status="failed", error=str(exc))
            return report
        result = self.ssh.run_script(
            self.config.remote_prepare_script,
            self._payload("dry-run"),
            timeout=120,
        )
        parsed = self._parse_json_result(result.stdout)
        note("Ubuntu dry-run", result.ok, result.stderr.strip() if not result.ok else "OK")
        for check in parsed.get("checks") or []:
            if isinstance(check, dict):
                note(str(check.get("name")), bool(check.get("ok")), str(check.get("detail") or ""))
        report["ok"] = all(item["ok"] for item in report["checks"])
        report["remote"] = parsed
        self.progress.write(
            status="success" if report["ok"] else "failed",
            message="Dry run complete" if report["ok"] else "Dry run found problems",
        )
        return report

    def _stream_backup(self, archive_path: Path) -> int:
        stdin_data = json.dumps(self._payload("backup")).encode("utf-8")
        process = self.ssh.popen(
            ["sudo", "-n", self.config.remote_prepare_script],
            stdin_bytes=stdin_data,
        )

        def on_progress(written: int, speed: float) -> None:
            self.progress.write(
                phase="transferring",
                message="Transferring backup…",
                bytes_done=written,
                speed_bps=int(speed),
            )

        try:
            written = stream_copy(
                process,
                archive_path,
                should_cancel=self.progress.cancel_requested,
                on_progress=on_progress,
            )
        except TransferCancelled as exc:
            raise BackupCancelled(str(exc)) from exc
        return written

    def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return self.dry_run()
        dest = Path(self.config.backup_destination)
        info: dict[str, Any] = {
            "backup_id": self.backup_id,
            "timestamp": self._started.strftime("%Y-%m-%d %H:%M:%S"),
            "source_ip": self.config.server_ip,
            "source_hostname": None,
            "application_version": __version__,
            "backup_size": 0,
            "sha256": None,
            "start_time": self._started.isoformat(timespec="seconds"),
            "finish_time": None,
            "duration_seconds": None,
            "status": "RUNNING",
            "website_directories": list(self.config.website_directories),
            "ojs_private_files": self.config.ojs_private_files,
            "databases": self.config.databases_for_backup(),
            "nginx_configuration": self.config.nginx_directory,
            "extra_directories": list(self.config.extra_directories),
            "errors": [],
            "warnings": [],
            "mode": self.mode,
        }
        status = "FAILED"
        error_message = ""
        try:
            prune_logs(self.config.log_directory, self.config.log_retention_days)
            self.logger.info(f"Backup start {self.backup_id} mode={self.mode}")
            self.progress.write(
                status="running",
                phase="lock",
                backup_id=self.backup_id,
                message="Checking whether another backup is running…",
                steps=[],
            )
            self.lock.acquire(mode=self.mode, backup_id=self.backup_id)
            self._check_cancel()
            self._validate_config_paths()

            self.progress.write(phase="storage", message="Checking backup drive…")
            drive = drive_status(dest)
            if not drive.exists:
                raise BackupError(drive.error or "Backup drive is unavailable.")
            self.progress.add_step("Backup drive", True, drive.path)
            if drive.free_gb < self.config.min_free_disk_gb:
                raise BackupError("Insufficient disk space.")
            self.progress.add_step("Windows free space", True, f"{drive.free_gb:.1f} GB available")

            ensure_directory(dest)
            self.incomplete_dir = dest / f".incomplete_{self.backup_id}"
            self.final_dir = dest / self.backup_id
            if self.incomplete_dir.exists():
                shutil.rmtree(self.incomplete_dir)
            self.incomplete_dir.mkdir(parents=True, exist_ok=True)

            self.progress.write(phase="ssh", message="Connecting to Ubuntu…")

            def _login() -> None:
                result = self.ssh.test_login()
                if not result.ok:
                    raise SSHError(result.stderr.strip() or "SSH login failed.")

            self._retry("SSH connectivity", _login)
            self.progress.add_step("Connected", True, self.config.server_ip)

            self.progress.write(phase="remote-check", message="Checking Ubuntu disk space and services…")

            def _check() -> dict[str, Any]:
                result = self.ssh.run_script(
                    self.config.remote_prepare_script,
                    self._payload("check"),
                    timeout=120,
                )
                if not result.ok:
                    raise BackupError(result.stderr.strip() or result.stdout.strip() or "Remote check failed.")
                return self._parse_json_result(result.stdout)

            remote = self._retry("Ubuntu pre-checks", _check)
            hostname = str(remote.get("hostname") or "")
            info["source_hostname"] = hostname or None
            if remote.get("free_gb") is not None and float(remote["free_gb"]) < self.config.min_remote_free_disk_gb:
                raise BackupError("Insufficient disk space.")
            self.progress.add_step("Ubuntu disk space", True, f"{remote.get('free_gb', '?')} GB free")
            self.progress.add_step("Required directories", True)
            self.progress.add_step("MariaDB", True, "Online dump (no service stop)")

            self._remote_work_id = str(self._payload("backup")["work_id"])
            archive_path = self.incomplete_dir / "server-backup.tar.gz"
            self.progress.write(phase="prepare", message="Preparing backup on Ubuntu…")
            self.progress.add_step("Preparing MariaDB / website files / Nginx", True, "Streaming archive")

            self.progress.write(phase="transferring", message="Transferring backup…")
            if self.transfer_fn is not None:
                written = self._retry("Backup transfer", lambda: self.transfer_fn(archive_path))
            else:
                written = self._retry("Backup transfer", lambda: self._stream_backup(archive_path))
            info["backup_size"] = written
            self.progress.add_step("Transfer", True, f"{written} bytes")

            self.progress.write(phase="verify", message="Verifying…")
            verify_archive(
                archive_path,
                website_directories=self.config.website_directories,
                ojs_private_files=self.config.ojs_private_files,
                nginx_directory=self.config.nginx_directory,
                databases=self.config.databases_for_backup(),
            )
            self.progress.add_step("Archive integrity", True)

            digest = sha256_file(archive_path)
            info["sha256"] = digest
            self.progress.write(sha256=digest)
            self.progress.add_step("SHA-256", True, digest)
            self.logger.info(f"SHA-256 {digest}")

            log_copy = self.incomplete_dir / "backup.log"
            if Path(self.logger.path).is_file():
                shutil.copy2(self.logger.path, log_copy)

            finished = datetime.now()
            info["finish_time"] = finished.isoformat(timespec="seconds")
            info["duration_seconds"] = int((finished - self._started).total_seconds())
            info["status"] = "SUCCESS"
            info["warnings"] = list(self.warnings)
            write_backup_info(self.incomplete_dir, info)

            os.replace(self.incomplete_dir, self.final_dir)
            self.incomplete_dir = None
            status = "SUCCESS"
            self.logger.info(f"Backup finalized {self.final_dir}")
            if self.final_dir and Path(self.logger.path).is_file():
                shutil.copy2(self.logger.path, self.final_dir / "backup.log")

            self.progress.write(phase="retention", message="Applying retention…")
            removed = apply_retention(dest, self.config.retention_count)
            self.progress.add_step(
                "Retention",
                True,
                f"Kept {self.config.retention_count}; removed {len(removed)} old backup(s)",
            )
            self.progress.write(
                status="success",
                phase="complete",
                message="BACKUP COMPLETED SUCCESSFULLY",
            )
            save_state(
                {
                    "last_backup": info["timestamp"],
                    "last_status": "SUCCESS",
                    "last_size": written,
                    "last_id": self.backup_id,
                    "last_sha256": digest,
                }
            )
            try:
                self.ssh.run_script(
                    self.config.remote_prepare_script,
                    {"action": "cleanup", "work_id": self._remote_work_id},
                    timeout=120,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"Remote cleanup warning: {exc}")
            self._remote_work_id = None
            return info
        except BackupAlreadyRunning:
            self.progress.write(status="failed", message="Backup already in progress.", error="Backup already in progress.")
            self.logger.error("Backup already in progress.")
            raise
        except BackupCancelled as exc:
            status = "CANCELLED"
            error_message = str(exc)
            self.errors.append(error_message)
            self.logger.info("Backup cancelled by user")
            self._cleanup_incomplete()
            self.progress.write(status="cancelled", message="Backup cancelled.", error=error_message)
            save_state({"last_status": "CANCELLED", "last_backup": info["timestamp"]})
            raise
        except (BackupError, SSHError, ArchiveIntegrityError, PathValidationError, OSError) as exc:
            status = "FAILED"
            error_message = str(exc)
            self.errors.append(error_message)
            self.logger.error(error_message)
            self._cleanup_incomplete()
            self.progress.write(status="failed", message=error_message, error=error_message)
            save_state({"last_status": "FAILED", "last_backup": info["timestamp"], "last_error": error_message})
            raise BackupError(error_message) from exc
        finally:
            info["status"] = status if status != "RUNNING" else "FAILED"
            info["errors"] = list(self.errors)
            info["warnings"] = list(self.warnings)
            if status != "SUCCESS":
                info["finish_time"] = datetime.now().isoformat(timespec="seconds")
                info["duration_seconds"] = int((datetime.now() - self._started).total_seconds())
            self.lock.release()
            self.logger.info(f"Backup finished status={info['status']}")
            self.logger.close()
