import subprocess
import sys
from pathlib import Path

from app.ssh.client import bundled_ubuntu_scripts
from tests.helpers import UBUNTU_SCRIPTS

if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))
import prepare_backup  # noqa: E402


def _run_helper(payload: str) -> subprocess.CompletedProcess[str]:
    script = bundled_ubuntu_scripts() / "prepare-backup.sh"
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(script.parent),
    )


def test_prepare_helper_rejects_empty_action():
    result = _run_helper("{}")
    assert result.returncode != 0
    assert "action not allowed" in (result.stderr + result.stdout)


def test_prepare_helper_accepts_master_actions():
    for action in (
        "discover-ojs",
        "inventory",
        "hash-files",
        "stream-objects",
        "database-fingerprint",
        "dump-databases",
        "discover-applications",
        "ensure-backup-mysql-user",
    ):
        result = _run_helper(f'{{"action":"{action}"}}')
        combined = result.stderr + result.stdout
        assert "action not allowed" not in combined, action


def test_prepare_helper_accepts_existing_check_action():
    result = _run_helper('{"action":"check"}')
    combined = result.stderr + result.stdout
    assert "action not allowed" not in combined
    assert '"hostname"' in result.stdout or '"checks"' in result.stdout or result.returncode in {0, 1}


def test_restore_helper_wrapper_does_not_use_heredoc_for_stdin():
    text = (bundled_ubuntu_scripts() / "restore-backup.sh").read_text(encoding="utf-8")
    assert "python3 - <<" not in text
    assert '"$PYTHON" -c' in text


def test_ubuntu_helper_scripts_use_lf_and_env_bash_shebang():
    from app.ssh.client import UBUNTU_HELPER_FILES, bundled_ubuntu_scripts, unix_text_bytes

    root = bundled_ubuntu_scripts()
    for name in UBUNTU_HELPER_FILES:
        data = (root / name).read_bytes()
        assert b"\r" not in data, name
        if name.endswith(".sh"):
            assert data.startswith(b"#!/usr/bin/env bash\n"), name


def test_unix_text_bytes_strips_crlf_from_env_bash_shebang():
    from app.ssh.client import unix_text_bytes

    raw = b"#!/usr/bin/env bash\r\necho hi\r\n"
    fixed = unix_text_bytes(raw)
    assert fixed == b"#!/usr/bin/env bash\necho hi\n"
    assert b"bash\r" not in fixed


def test_path_checks_treat_missing_website_and_ojs_fallback_as_ok(tmp_path, monkeypatch):
    nginx = tmp_path / "nginx"
    nginx.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    present_site = tmp_path / "present-site"
    present_site.mkdir()
    monkeypatch.setattr(prepare_backup.shutil, "which", lambda name: f"/usr/bin/{name}")

    checks = prepare_backup.path_checks(
        {
            "website_directories": ["/var/www/50sea.com", str(present_site)],
            "ojs_private_files": "/var/www/ojs-files",
            "nginx_directory": str(nginx),
            "extra_directories": [str(extra), "/var/www/missing-extra"],
        }
    )
    by_name = {item["name"]: item for item in checks}

    missing_site = by_name["website /var/www/50sea.com"]
    assert missing_site["ok"] is True
    assert "legacy fallback" in missing_site["detail"]
    assert "/var/www/50sea.com" in missing_site["detail"]

    present = by_name[f"website {present_site}"]
    assert present["ok"] is True
    assert present["detail"] == str(present_site)

    missing_ojs = by_name["OJS private files /var/www/ojs-files"]
    assert missing_ojs["ok"] is True
    assert "legacy fallback" in missing_ojs["detail"]

    assert by_name["Nginx"]["ok"] is True
    assert by_name[f"extra {extra}"]["ok"] is True
    assert by_name["extra /var/www/missing-extra"]["ok"] is False
    assert by_name["MariaDB client"]["ok"] is True
    assert by_name["tar/gzip"]["ok"] is True


def test_path_checks_still_fail_missing_nginx(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_backup.shutil, "which", lambda name: f"/usr/bin/{name}")
    checks = prepare_backup.path_checks(
        {
            "website_directories": [],
            "nginx_directory": "/etc/nginx-does-not-exist",
        }
    )
    nginx = next(item for item in checks if item["name"] == "Nginx")
    assert nginx["ok"] is False
    assert "missing:" in nginx["detail"]


def test_upload_unix_text_never_sends_crlf(tmp_path, monkeypatch):
    from app.config.schema import AppConfig
    from app.ssh.client import SSHClient, SSHResult

    source = tmp_path / "prepare-backup.sh"
    source.write_bytes(b"#!/usr/bin/env bash\r\necho hi\r\n")
    sent: list[bytes] = []

    def fake_scp(self, local, remote):
        sent.append(Path(local).read_bytes())
        return SSHResult(0, "", "")

    monkeypatch.setattr(SSHClient, "scp_upload", fake_scp)
    client = SSHClient(AppConfig())
    result = client._upload_unix_text(source, "/tmp/prepare-backup.sh")
    assert result.ok
    assert sent == [b"#!/usr/bin/env bash\necho hi\n"]