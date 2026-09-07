"""Application configuration schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

SYSTEM_DATABASES = frozenset(
    {
        "information_schema",
        "performance_schema",
        "mysql",
        "sys",
    }
)


@dataclass
class AppConfig:
    server_ip: str = "192.168.18.18"
    ssh_username: str = "zhz"
    ssh_port: int = 22
    ssh_private_key_path: str = ""
    backup_destination: str = r"G:\ServerBackups"
    log_directory: str = r"C:\ServerBackup\Logs"
    retention_count: int = 5
    retry_count: int = 3
    retry_delay_seconds: int = 30
    min_free_disk_gb: float = 20.0
    min_remote_free_disk_gb: float = 5.0
    compression_level: int = 6
    website_directories: list[str] = field(
        default_factory=lambda: [
            "/var/www/journal.50sea.com",
            "/var/www/journal.xdgen.com",
            "/var/www/xdgen.com",
        ]
    )
    ojs_private_files: str = "/var/www/ojs-files"
    nginx_directory: str = "/etc/nginx"
    extra_directories: list[str] = field(default_factory=list)
    selected_databases: list[str] = field(default_factory=list)
    exclude_system_databases: bool = True
    log_retention_days: int = 90
    automatic_backup: bool = False
    schedule_type: str = "daily"
    schedule_time: str = "02:00"
    schedule_weekday: str = "Sunday"
    remote_prepare_script: str = "/usr/local/lib/serverbackup/prepare-backup.sh"
    remote_restore_script: str = "/usr/local/lib/serverbackup/restore-backup.sh"
    remote_security_script: str = "/usr/local/lib/serverbackup/security-audit.sh"
    security_store: str = r"C:\ServerBackup\Security"
    security_mode: str = "BALANCED"
    ssh_connect_timeout: int = 20
    transfer_timeout: int = 6 * 60 * 60
    security_audit_timeout: int = 180

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        cfg = cls()
        for key, value in filtered.items():
            setattr(cfg, key, value)
        cfg.retention_count = max(1, int(cfg.retention_count))
        cfg.retry_count = max(1, int(cfg.retry_count))
        cfg.retry_delay_seconds = max(1, int(cfg.retry_delay_seconds))
        cfg.ssh_port = int(cfg.ssh_port)
        cfg.compression_level = min(9, max(1, int(cfg.compression_level)))
        cfg.security_audit_timeout = max(30, int(cfg.security_audit_timeout))
        cfg.website_directories = [str(p) for p in cfg.website_directories]
        cfg.extra_directories = [str(p) for p in cfg.extra_directories]
        cfg.selected_databases = [str(p) for p in cfg.selected_databases]
        cfg.automatic_backup = bool(cfg.automatic_backup)
        mode = str(cfg.security_mode or "BALANCED").upper()
        if mode not in {"LOW", "BALANCED", "HIGH", "CRITICAL"}:
            mode = "BALANCED"
        cfg.security_mode = mode
        return cfg

    def databases_for_backup(self) -> list[str]:
        names = list(self.selected_databases)
        if self.exclude_system_databases:
            names = [n for n in names if n not in SYSTEM_DATABASES]
        return names
