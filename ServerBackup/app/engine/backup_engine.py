"""Single backup engine used by BACKUP NOW and Task Scheduler.

Version 1.4.0 writes a content-addressed master at <destination>/master/.
It never stops Nginx, PHP-FPM, or MariaDB and never mutates production
website files or databases. Restore is a separate confirmed flow.

Existing G:\\ServerBackups\\YYYY-MM-DD_HHMMSS\\ archives are left untouched.
Master does not use keep-5 retention and does not rebuild a giant tar.gz
for every run.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app import __version__
from app.backup.lock import BackupAlreadyRunning, BackupLock
from app.backup.progress import ProgressReporter
from app.config.schema import AppConfig
from app.config.store import runtime_dir, save_state
from app.logutil.logger import BackupLogger, prune_logs
from app.master.pipeline import PipelineError, run_master_backup
from app.master.store import MasterStore
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
                if self._is_auth_failure(exc):
                    self.progress.write(status="failed", message=str(exc), error=str(exc))
                    raise
                if attempt < attempts:
                    self.progress.write(
                        message=(
                            f"{label} failed: {exc}. Retrying in {delay}s "
                            f"(attempt {attempt}/{attempts})"
                        )
                    )
                    time.sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_auth_failure(exc: BaseException) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "wrong username or password",
                "authentication failed",
                "permission denied",
                "password is required",
                "a terminal is required",
            )
        )

    def _validate_config_paths(self) -> None:
        for directory in self.config.website_directories:
            validate_unix_path(directory, field="website directory")
        if self.config.ojs_private_files:
            validate_unix_path(self.config.ojs_private_files, field="OJS private-files directory")
        validate_unix_path(self.config.nginx_directory, field="Nginx directory")
        for directory in self.config.extra_directories:
            validate_unix_path(directory, field="additional directory")
        validate_unix_path(self.config.remote_prepare_script, field="remote prepare script")

    def _cleanup_remote(self) -> None:
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
        decoder = json.JSONDecoder()
        best: dict[str, Any] = {}
        index = 0
        helper_keys = {
            "ok",
            "installations",
            "applications",
            "files",
            "hostname",
            "fingerprints",
            "hashes",
            "dumps",
            "checks",
            "databases",
            "error",
        }
        while True:
            brace = text.find("{", index)
            if brace == -1:
                break
            try:
                data, _end = decoder.raw_decode(text, brace)
            except json.JSONDecodeError:
                index = brace + 1
                continue
            if isinstance(data, dict) and (helper_keys & set(data.keys())):
                best = data
            index = brace + 1
        return best

    def _stream_backup(self, archive_path: Path) -> int:
        """Legacy 1.3.7 tar stream. Kept for SSH/Paramiko regression tests only."""
        from app.backup.transfer import TransferCancelled, stream_copy

        process = self.ssh.popen_script(
            self.config.remote_prepare_script,
            self._payload("backup"),
        )

        def on_progress(written: int, speed: float) -> None:
            self.progress.write(
                phase="transferring",
                message="Transferring backup…",
                bytes_done=written,
                speed_bps=int(speed),
            )

        try:
            return stream_copy(
                process,
                archive_path,
                should_cancel=self.progress.cancel_requested,
                on_progress=on_progress,
            )
        except TransferCancelled as exc:
            raise BackupCancelled(str(exc)) from exc

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
            helpers = self.ssh.ensure_remote_scripts()
            if helpers.ok and helpers.stderr == "installed Ubuntu backup helpers":
                results["details"].append("Installed Ubuntu backup helpers")
            elif not helpers.ok:
                results["details"].append(helpers.stderr.strip() or "Could not install Ubuntu backup helpers.")
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
            elif SSHClient._sudo_password_required(check):
                results["details"].append(
                    check.stderr.strip()
                    or "SSH login succeeded, but sudo needs the Ubuntu password."
                )
            elif SSHClient._script_missing(check):
                results["details"].append(
                    check.stderr.strip()
                    or "Backup helpers are not installed on Ubuntu."
                )
            else:
                results["details"].append(
                    check.stderr.strip()
                    or "Backup script could not be executed."
                )
        except SSHError as exc:
            results["details"].append(str(exc))
            self.logger.error(f"Connection test failed: {exc}")
        finally:
            closer = getattr(self.ssh, "close", None)
            if callable(closer):
                closer()
        return results

    def dry_run(self) -> dict[str, Any]:
        report: dict[str, Any] = {"ok": False, "checks": [], "report_text": ""}

        def note(name: str, ok: bool, detail: str = "") -> None:
            report["checks"].append({"name": name, "ok": ok, "detail": detail})
            self.progress.add_step(name, ok, detail)

        def stage(token: str, message: str, pct: int) -> None:
            self.logger.info(token)
            self.progress.write(
                status="running",
                phase="dry-run",
                backup_id=self.backup_id,
                message=message,
                bytes_done=pct,
                bytes_total=100,
            )

        try:
            self.lock.acquire(mode="dry-run", backup_id=self.backup_id)
            stage("DRY_RUN_START", "Dry run started…", 1)
            self._check_cancel()
            has_password = bool(getattr(self.ssh, "password", None))
            self.logger.info(
                f"DRY_RUN_PASSWORD_CHECK in_memory_password={'yes' if has_password else 'no'} "
                f"transport={getattr(self.ssh, 'transport_name', lambda: 'unknown')()} "
                f"user={self.config.ssh_username} host={self.config.server_ip}"
            )
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
                report["error"] = str(exc)
                report["report_text"] = str(exc)
                self.logger.error(f"DRY_RUN_ERROR {exc}")
                self.progress.write(status="failed", error=str(exc), message=str(exc))
                return report
            stage("DRY_RUN_SSH_CONNECT_START", "Connecting to Ubuntu…", 10)
            try:
                login = self.ssh.test_login()
                note("SSH", login.ok, login.stderr.strip() if not login.ok else "OK")
            except SSHError as exc:
                note("SSH", False, str(exc))
                report["ok"] = False
                report["error"] = str(exc)
                report["report_text"] = str(exc)
                self.logger.error(f"DRY_RUN_ERROR {exc}")
                self.progress.write(status="failed", error=str(exc), message=str(exc))
                return report
            if not login.ok:
                report["ok"] = False
                report["error"] = login.stderr.strip() or "SSH login failed."
                report["report_text"] = report["error"]
                self.logger.error(f"DRY_RUN_ERROR {report['error']}")
                self.progress.write(status="failed", error=report["error"], message=report["error"])
                return report
            stage("DRY_RUN_SSH_CONNECTED", "SSH connected.", 20)
            helpers = self.ssh.ensure_remote_scripts()
            if helpers.ok and helpers.stderr == "installed Ubuntu backup helpers":
                note("Ubuntu helpers", True, "installed")
            elif not helpers.ok:
                note("Ubuntu helpers", False, helpers.stderr.strip())
                report["ok"] = False
                report["error"] = helpers.stderr.strip()
                report["report_text"] = report["error"]
                self.logger.error(f"DRY_RUN_ERROR {report['error']}")
                self.progress.write(status="failed", error=report["error"], message=report["error"])
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
            self._check_cancel()
            try:
                master = run_master_backup(self, dry_run=True)
            except BackupCancelled:
                raise
            except (PipelineError, SSHError) as exc:
                note("Master delta preview", False, str(exc))
                report["ok"] = False
                report["error"] = str(exc)
                report["report_text"] = str(exc)
                self.logger.error(f"DRY_RUN_ERROR {exc}")
                self.progress.write(status="failed", error=str(exc), message=str(exc))
                return report
            report["master"] = master
            report["report_text"] = str(master.get("report_text") or "")
            counts = master.get("counts") or {}
            note(
                "Master delta",
                True,
                (
                    f"{master.get('type')} NEW={counts.get('new', 0)} "
                    f"MODIFIED={counts.get('modified', 0)} DELETED={counts.get('deleted', 0)} "
                    f"RENAMED={counts.get('renamed', 0)} MOVED={counts.get('moved', 0)} "
                    f"DB={master.get('database')}"
                ),
            )
            report["ok"] = all(item["ok"] for item in report["checks"]) and bool(master.get("ok", True))
            report["remote"] = parsed
            if not report["ok"] and master.get("error"):
                report["error"] = master.get("error")
            message = (
                "Dry run complete. HEAD unchanged."
                if report["ok"]
                else (report.get("error") or "Dry run found problems")
            )
            self.progress.write(
                status="success" if report["ok"] else "failed",
                message=message,
                bytes_done=100,
                bytes_total=100,
            )
            if not report["ok"]:
                self.logger.error(f"DRY_RUN_ERROR {message}")
            return report
        except BackupAlreadyRunning:
            self.logger.error("DRY_RUN_ERROR Backup already in progress.")
            raise
        except BackupCancelled as exc:
            self.logger.info("DRY_RUN_ERROR cancelled")
            self.progress.write(status="cancelled", message=str(exc), error=str(exc))
            raise
        except Exception as exc:
            self.logger.error(f"DRY_RUN_ERROR {exc}")
            self.progress.write(status="failed", message=str(exc), error=str(exc))
            if isinstance(exc, BackupError):
                raise
            raise BackupError(str(exc)) from exc
        finally:
            self.lock.release()
            closer = getattr(self.ssh, "close", None)
            if callable(closer):
                closer()

    def rebuild_master(self) -> dict[str, Any]:
        return self.run(rebuild=True)

    def run(self, *, dry_run: bool = False, rebuild: bool = False) -> dict[str, Any]:
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
            "master": True,
        }
        status = "FAILED"
        error_message = ""
        try:
            prune_logs(self.config.log_directory, self.config.log_retention_days)
            self.logger.info(f"Master backup start {self.backup_id} mode={self.mode} rebuild={rebuild}")
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
            MasterStore(dest).ensure_layout()

            self.progress.write(phase="ssh", message="Connecting to Ubuntu…")
            self.logger.info(
                f"BACKUP NOW SSH transport={getattr(self.ssh, 'transport_name', lambda: 'unknown')()} "
                f"user={self.config.ssh_username} host={self.config.server_ip}"
            )
            self._remote_work_id = str(self._payload("inventory")["work_id"])
            result = run_master_backup(self, rebuild=rebuild)
            info.update(result)
            info["backup_size"] = int(result.get("bytes_transferred") or 0)
            info["status"] = "SUCCESS"
            finished = datetime.now()
            info["finish_time"] = finished.isoformat(timespec="seconds")
            info["duration_seconds"] = int((finished - self._started).total_seconds())
            status = "SUCCESS"
            self.logger.info(
                f"Master {result.get('type')} generation={result.get('generation')} "
                f"bytes={result.get('bytes_transferred')}"
            )
            # Master never uses keep-5 retention and never deletes YYYY-MM-DD archives.
            self.progress.write(
                status="success",
                phase="complete",
                message=str((self.progress.read() or {}).get("message") or "MASTER BACKUP STATUS=SUCCESS"),
            )
            save_state(
                {
                    "last_backup": info["timestamp"],
                    "last_status": "SUCCESS",
                    "last_size": info["backup_size"],
                    "last_id": self.backup_id,
                    "last_type": result.get("type"),
                    "last_generation": result.get("generation"),
                }
            )
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
            self._cleanup_remote()
            self.progress.write(status="cancelled", message="Backup cancelled.", error=error_message)
            save_state({"last_status": "CANCELLED", "last_backup": info["timestamp"]})
            raise
        except (BackupError, SSHError, PipelineError, PathValidationError, OSError, ValueError) as exc:
            if "cancelled" in str(exc).lower():
                status = "CANCELLED"
                error_message = str(exc)
                self.errors.append(error_message)
                self._cleanup_remote()
                self.progress.write(status="cancelled", message="Backup cancelled.", error=error_message)
                save_state({"last_status": "CANCELLED", "last_backup": info["timestamp"]})
                raise BackupCancelled(error_message) from exc
            status = "FAILED"
            error_message = str(exc)
            self.errors.append(error_message)
            self.logger.error(error_message)
            self._cleanup_remote()
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
            closer = getattr(self.ssh, "close", None)
            if callable(closer):
                closer()
            self.logger.info(f"Backup finished status={info['status']}")
            self.logger.close()
