from __future__ import annotations

import subprocess
import time
from io import BytesIO
from pathlib import Path

import pytest

from app.backup.live import BackupLiveSession, UI_FAILED, UI_INVENTORY, format_live_backup_panel
from app.backup.progress import ProgressReporter
from app.config.schema import AppConfig
from app.ssh.client import SSHClient, SSHError
from app.ssh.timeouts import IdleTimeoutStream, SSHCommandTimeout, command_timeout_for, idle_timeout_for


class _SlowChunks:
    def __init__(self, chunks: list[bytes], delay: float) -> None:
        self.chunks = list(chunks)
        self.delay = delay

    def read(self, _size: int = -1) -> bytes:
        time.sleep(self.delay)
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class _HangForever:
    def read(self, _size: int = -1) -> bytes:
        time.sleep(30)
        return b""


def test_helper_timeouts_are_not_the_connect_timeout():
    cfg = AppConfig(ssh_connect_timeout=20)
    assert command_timeout_for("test_login", cfg) == 20
    assert command_timeout_for("discover-applications", cfg) == cfg.ssh_discovery_timeout
    assert command_timeout_for("discover-ojs", cfg) == cfg.ssh_discovery_timeout
    assert command_timeout_for("inventory", cfg) == cfg.transfer_timeout
    assert command_timeout_for("hash-files", cfg) == cfg.transfer_timeout
    assert command_timeout_for("database-fingerprint", cfg) == cfg.ssh_fingerprint_timeout
    assert command_timeout_for("install_helper", cfg) == cfg.ssh_install_timeout
    assert command_timeout_for("discover-applications", cfg) > cfg.ssh_connect_timeout
    assert command_timeout_for("inventory", cfg) > cfg.ssh_connect_timeout
    assert idle_timeout_for("stream-objects", cfg) == cfg.ssh_idle_timeout
    assert idle_timeout_for("dump-databases", cfg) >= 900


def test_openssh_run_uses_action_timeout_not_connect_timeout(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    cfg = AppConfig(ssh_connect_timeout=20, ssh_private_key_path="")
    client = SSHClient(cfg, runner=fake_run)
    client.run(["printf", "ok"], action="test_login")
    assert captured["timeout"] == 20
    client.run(["/usr/local/lib/serverbackup/prepare-backup.sh"], action="inventory")
    assert captured["timeout"] == cfg.transfer_timeout
    assert captured["timeout"] != 20
    client.run(["/usr/local/lib/serverbackup/prepare-backup.sh"], action="discover-applications")
    assert captured["timeout"] == cfg.ssh_discovery_timeout
    client.run(["/usr/local/lib/serverbackup/prepare-backup.sh"], action="inventory", timeout=99)
    assert captured["timeout"] == 99


def test_openssh_timeout_error_names_the_action(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    logs: list[str] = []

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=kwargs.get("timeout") or 20)

    cfg = AppConfig(ssh_connect_timeout=20, ssh_private_key_path="")
    client = SSHClient(cfg, runner=fake_run)
    client.logger = type("L", (), {"info": lambda self, message: logs.append(message)})()
    with pytest.raises(SSHError) as caught:
        client.run(["slow-command"], action="discover-applications")
    text = str(caught.value)
    assert "SSH command timed out" in text
    assert "discover-applications" in text
    assert "timeout=1800" in text or "timeout=1800.0" in text
    assert any("SSH_COMMAND_START action=discover-applications" in line for line in logs)
    assert any("SSH_COMMAND_TIMEOUT action=discover-applications" in line for line in logs)
    assert all("password" not in line.lower() or "[REDACTED]" in line for line in logs)


def test_paramiko_inventory_does_not_use_connect_timeout(monkeypatch):
    captured: dict = {}

    class Fake:
        def exec_command(self, command, timeout=None):
            captured["timeout"] = timeout
            channel = type(
                "Chan",
                (),
                {
                    "recv_exit_status": staticmethod(lambda: 0),
                    "shutdown_write": staticmethod(lambda: None),
                },
            )()

            class Stdin:
                def write(self, _data):
                    return None

                def flush(self):
                    return None

                @property
                def channel(self):
                    return channel

            class Stdout:
                def __init__(self) -> None:
                    self.channel = channel

                def read(self):
                    return b'{"ok":true,"files":[]}'

            return Stdin(), Stdout(), BytesIO(b"")

        def get_transport(self):
            return None

        def open_sftp(self):
            raise AssertionError("not used")

        def close(self):
            return None

    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: Fake())
    cfg = AppConfig(ssh_connect_timeout=20, ssh_private_key_path="")
    client = SSHClient(cfg, password="secret")
    client._sudo_askpass = "/tmp/serverbackup-sudo.askpass"
    client._sudo_pwfile = "/tmp/serverbackup-sudo.pw"
    monkeypatch.setattr(SSHClient, "_remove_remote_file", lambda self, remote: None)
    result = client.run_script(cfg.remote_prepare_script, {"action": "inventory"})
    assert result.ok
    assert captured["timeout"] == cfg.transfer_timeout
    assert captured["timeout"] != 20


def test_paramiko_stream_exec_has_no_total_command_timeout(monkeypatch):
    captured: dict = {}

    class Fake:
        def get_transport(self):
            parent = self

            class Transport:
                def open_session(self):
                    class Channel:
                        def exec_command(self, command, timeout=None):
                            captured["command"] = command
                            captured["timeout"] = timeout

                        def settimeout(self, value):
                            captured["channel_timeout"] = value

                        def sendall(self, data):
                            captured["sent"] = data

                        def shutdown_write(self):
                            return None

                        def makefile(self, mode, bufsize=0):
                            return BytesIO(b"STREAM")

                        def makefile_stderr(self, mode, bufsize=0):
                            return BytesIO(b"")

                        def recv_exit_status(self):
                            return 0

                        def exit_status_ready(self):
                            return True

                        def close(self):
                            captured["closed"] = True

                    return Channel()

                def set_keepalive(self, interval):
                    captured["keepalive"] = interval

            return Transport()

        def close(self):
            return None

    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: Fake())
    cfg = AppConfig(ssh_connect_timeout=20, ssh_idle_timeout=300, ssh_private_key_path="")
    client = SSHClient(cfg, password="secret")
    client._sudo_askpass = "/tmp/serverbackup-sudo.askpass"
    client._sudo_pwfile = "/tmp/serverbackup-sudo.pw"
    monkeypatch.setattr(SSHClient, "_remove_remote_file", lambda self, remote: None)
    proc = client.popen_script(
        cfg.remote_prepare_script,
        {"action": "stream-objects", "files": [], "allowed_roots": []},
    )
    assert "timeout" not in captured or captured.get("timeout") is None
    assert captured.get("channel_timeout") == 300
    data = proc.stdout.read()
    assert data == b"STREAM"
    client.close()
    assert captured.get("closed") is True


def test_streaming_activity_is_not_a_total_timeout():
    raw = _SlowChunks([b"aaaa", b"bbbb", b"cccc", b""], delay=0.05)
    stream = IdleTimeoutStream(raw, action="stream-objects", idle_timeout=0.45)
    started = time.monotonic()
    data = stream.read()
    elapsed = time.monotonic() - started
    assert data == b"aaaabbbbcccc"
    assert elapsed >= 0.15
    assert elapsed < 2.0
    started2 = time.monotonic()
    assert stream.read() == b""
    assert time.monotonic() - started2 < 0.2


def test_true_idle_timeout_kills_hung_command():
    killed = {"n": 0}

    def on_kill():
        killed["n"] += 1

    stream = IdleTimeoutStream(
        _HangForever(),
        action="stream-objects",
        idle_timeout=0.2,
        on_kill=on_kill,
    )
    started = time.monotonic()
    with pytest.raises(SSHCommandTimeout) as caught:
        stream.read()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert caught.value.action == "stream-objects"
    assert caught.value.kind == "idle"
    assert killed["n"] == 1


def test_keepalive_options_are_on_openssh_argv(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    args = " ".join(SSHClient(cfg)._base_ssh_args())
    assert "ServerAliveInterval=15" in args
    assert "ServerAliveCountMax=4" in args
    assert "ConnectTimeout=20" in args


def test_failed_panel_shows_inventory_not_ssh(tmp_path: Path):
    reporter = ProgressReporter(tmp_path / "progress.json")
    live = BackupLiveSession(reporter, operation="BACKUP", backup_id="2026-09-08_183638")
    live.application = "journal.50sea.com"
    live.overall["files_total"] = 24000
    live.ssh_action = "inventory"
    live.set_ui_stage(UI_INVENTORY, "Building file inventory…", phase="inventory")
    live.finish(
        "failed",
        UI_FAILED,
        "BACKUP FAILED",
        error="SSH command timed out during inventory (elapsed=120.0s, timeout=120s, last_activity=120.0s ago, bytes=0).",
    )
    data = reporter.read()
    panel = format_live_backup_panel(data)
    assert "Stage: INVENTORY" in panel
    assert "Stage: ssh" not in panel
    assert "journal.50sea.com" in panel
    assert "24000" in panel
    assert "SSH action: inventory" in panel
    assert data.get("head_state") == "UNCHANGED"
    assert data.get("staging_state") == "CLEANED"
    assert data.get("last_stage") == UI_INVENTORY


def test_close_kills_active_stream(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    killed = {"n": 0}

    class FakeProc:
        def __init__(self) -> None:
            self.stdin = BytesIO()
            self.stdout = BytesIO(b"data")
            self.stderr = BytesIO(b"")
            self.returncode = None

        def kill(self):
            killed["n"] += 1

        def wait(self):
            return 0

    monkeypatch.setattr("app.ssh.client.subprocess.Popen", lambda *args, **kwargs: FakeProc())
    cfg = AppConfig(ssh_private_key_path="")
    client = SSHClient(cfg)
    client.popen(["cat"], action="stream-objects")
    client.close()
    assert killed["n"] == 1
    assert client._active_process is None
