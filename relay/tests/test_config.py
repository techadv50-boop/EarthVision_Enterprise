from pathlib import Path

import pytest

from relay.config import ConfigError, load_settings


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_sftp_source_and_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_PASSWORD", "source-secret")
    monkeypatch.setenv("DEST_PASSWORD", "dest-secret")
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
stability_seconds: 60
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: sftp
    host: server.example
    port: 21098
    username: cpanel
    password_env: SOURCE_PASSWORD
    remote_dir: /home/cpanel/drop
    deliver_to: archive
destinations:
  - id: archive
    protocol: sftp
    host: 203.0.113.10
    port: 22
    username: relay
    password_env: DEST_PASSWORD
    remote_dir: /srv/incoming
""",
    )
    settings = load_settings(config)
    assert settings.poll_interval_seconds == 60
    assert settings.local_ttl_hours == 24
    assert settings.sources[0].endpoint.password == "source-secret"
    assert settings.sources[0].endpoint.port == 21098
    assert settings.sources[0].deliver_to == ("archive",)
    assert settings.destinations_for(settings.sources[0])[0].id == "archive"
    assert "source-secret" not in repr(settings.sources[0].endpoint)


def test_deliver_to_all_and_a_list(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 1
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: drop-a
    protocol: ftps
    host: a.example
    port: 21
    username: a
    password: a-secret
    remote_dir: /drop
    deliver_to: all
  - id: drop-b
    protocol: sftp
    host: b.example
    port: 22
    username: b
    private_key_path: /keys/b
    remote_dir: /drop
    deliver_to: [archive, shared-copy]
destinations:
  - id: archive
    protocol: sftp
    host: vps.example
    port: 22
    username: relay
    private_key_path: /keys/archive
    remote_dir: /incoming
  - id: shared-copy
    protocol: ftps
    host: shared.example
    port: 21
    username: copy
    password: copy-secret
    remote_dir: /incoming
""",
    )
    settings = load_settings(config)
    assert settings.stability_seconds == 60
    assert settings.sources[0].deliver_to == "all"
    assert [item.id for item in settings.destinations_for(settings.sources[0])] == [
        "archive",
        "shared-copy",
    ]
    assert settings.sources[1].deliver_to == ("archive", "shared-copy")


def test_rejects_plain_ftp(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: ftp
    host: server.example
    port: 21
    username: cpanel
    password: secret
    remote_dir: /drop
    deliver_to: all
destinations:
  - id: archive
    protocol: sftp
    host: vps.example
    port: 22
    username: relay
    password: secret
    remote_dir: /incoming
""",
    )
    with pytest.raises(ConfigError, match="plain ftp"):
        load_settings(config)


def test_rejects_root_remote_dir(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: sftp
    host: server.example
    port: 22
    username: cpanel
    password: secret
    remote_dir: /
    deliver_to: archive
destinations:
  - id: archive
    protocol: sftp
    host: vps.example
    port: 22
    username: relay
    password: secret
    remote_dir: /incoming
""",
    )
    with pytest.raises(ConfigError, match="remote_dir"):
        load_settings(config)


def test_rejects_unknown_destination_and_missing_secret(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: sftp
    host: server.example
    port: 21098
    username: cpanel
    password: secret
    remote_dir: /drop
    deliver_to: [missing]
destinations:
  - id: archive
    protocol: sftp
    host: vps.example
    port: 22
    username: relay
    password: dest-secret
    remote_dir: /incoming
""",
    )
    with pytest.raises(ConfigError, match="unknown destinations"):
        load_settings(config)

    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("deliver_to: [missing]", "deliver_to: archive")
        .replace("    password: dest-secret\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="password or a private key"):
        load_settings(config)


def test_missing_password_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOURCE_PASSWORD", raising=False)
    config = _write(
        tmp_path / "config.yaml",
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: sftp
    host: server.example
    port: 21098
    username: cpanel
    password_env: SOURCE_PASSWORD
    remote_dir: /drop
    deliver_to: archive
destinations:
  - id: archive
    protocol: sftp
    host: vps.example
    port: 22
    username: relay
    password: secret
    remote_dir: /incoming
""",
    )
    with pytest.raises(ConfigError, match="SOURCE_PASSWORD"):
        load_settings(config)
