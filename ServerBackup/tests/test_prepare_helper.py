import subprocess
from pathlib import Path

from app.ssh.client import bundled_ubuntu_scripts


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


def test_prepare_helper_accepts_existing_check_action():
    result = _run_helper('{"action":"check"}')
    combined = result.stderr + result.stdout
    assert "action not allowed" not in combined
    assert '"hostname"' in result.stdout or '"checks"' in result.stdout or result.returncode in {0, 1}


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