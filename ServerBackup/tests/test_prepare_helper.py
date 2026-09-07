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