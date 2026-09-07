from pathlib import Path

from app.config.schema import AppConfig
from app.config.store import load_config, save_config
from app.security.paths import PathValidationError, is_safe_unix_path, validate_unix_path
from tests.helpers import make_config


def test_default_config_values():
    cfg = AppConfig()
    assert cfg.server_ip == "192.168.18.18"
    assert cfg.ssh_username == "zhz"
    assert cfg.retention_count == 5
    assert cfg.automatic_backup is False
    assert cfg.setup_completed is False
    assert cfg.security_mode == "BALANCED"
    assert cfg.retry_count == 3
    assert "/var/www/journal.50sea.com" in cfg.website_directories
    assert cfg.ojs_private_files == "/var/www/ojs-files"


def test_config_roundtrip(tmp_path: Path):
    cfg = make_config(tmp_path, retention_count=7, automatic_backup=False)
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.retention_count == 7
    assert loaded.automatic_backup is False
    assert loaded.backup_destination == cfg.backup_destination


def test_unix_path_validation():
    assert is_safe_unix_path("/var/www/xdgen.com")
    assert not is_safe_unix_path("/var/www/../../etc/passwd")
    assert not is_safe_unix_path("/var/www; rm -rf /")
    try:
        validate_unix_path("/tmp/evil|name")
        assert False, "should have failed"
    except PathValidationError:
        pass
