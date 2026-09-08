from io import BytesIO
from pathlib import Path

from app.config.schema import AppConfig
from app.ssh.client import SSHClient


class _FakeChannelFile:
    def __init__(self, data: bytes) -> None:
        self._buf = BytesIO(data)

    def read(self, *args):
        return self._buf.read(*args)

    def decode(self, *args, **kwargs):
        return self._buf.getvalue().decode(*args, **kwargs)


class _FakeStdout:
    def __init__(self, data: bytes, channel) -> None:
        self._buf = BytesIO(data)
        self.channel = channel

    def read(self, *args):
        return self._buf.read(*args)


class _FakeStdin:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.written = ""

    def write(self, data: str) -> int:
        self.written += data
        return len(data)

    def flush(self) -> None:
        return None


class FakeParamiko:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.password_seen = None

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        channel = type("Chan", (), {"recv_exit_status": staticmethod(lambda: 0), "shutdown_write": staticmethod(lambda: None)})()
        return _FakeStdin(channel), _FakeStdout(b"ok", channel), _FakeChannelFile(b"")

    def open_sftp(self):
        client = self
        store = getattr(self, "remote_files", {})
        self.remote_files = store
        self.removed = getattr(self, "removed", [])

        class _RemoteFile:
            def __init__(self, path: str) -> None:
                self.path = path
                self.buf = BytesIO()

            def write(self, data):
                if isinstance(data, str):
                    data = data.encode("utf-8")
                self.buf.write(data)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                store[self.path] = self.buf.getvalue()

        class SFTP:
            def put(self, local, remote):
                client.uploads.append((local, remote))

            def open(self, remote, mode="r"):
                return _RemoteFile(remote)

            def chmod(self, remote, mode):
                client.modes = getattr(client, "modes", {})
                client.modes[remote] = mode

            def remove(self, remote):
                client.removed.append(remote)
                store.pop(remote, None)

            def close(self):
                return None

        return SFTP()

    def get_transport(self):
        parent = self

        class Transport:
            def open_session(self):
                class Channel:
                    def __init__(self) -> None:
                        self._sent = b""

                    def exec_command(self, command):
                        parent.commands.append(command)

                    def sendall(self, data):
                        self._sent += data
                        parent.sent = getattr(parent, "sent", b"") + data

                    def shutdown_write(self):
                        return None

                    def makefile(self, mode, bufsize=0):
                        return BytesIO(b"archive-bytes")

                    def makefile_stderr(self, mode, bufsize=0):
                        return BytesIO(b"")

                    def recv_exit_status(self):
                        return 0

                    def exit_status_ready(self):
                        return True

                    def close(self):
                        return None

                return Channel()

        return Transport()


def test_password_is_not_stored_in_config():
    cfg = AppConfig()
    assert "password" not in cfg.to_dict()
    assert "ssh_password" not in cfg.to_dict()


def test_password_login_uses_paramiko_and_keeps_secret_off_argv(monkeypatch):
    fake = FakeParamiko()
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: fake)
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    client = SSHClient(cfg, password="super-secret")
    args = " ".join(client._base_ssh_args())
    assert "super-secret" not in args
    assert "BatchMode=yes" in args
    assert "SERVERBACKUP_ASKPASS" not in client.ssh_env()
    result = client.test_login()
    assert result.ok
    assert result.stdout == "ok"
    assert fake.commands
    assert "super-secret" not in " ".join(fake.commands)


def test_password_upload_uses_sftp(monkeypatch, tmp_path):
    fake = FakeParamiko()
    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: fake)
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    client = SSHClient(cfg, password="super-secret")
    local = tmp_path / "archive.tar.gz"
    local.write_bytes(b"data")
    result = client.scp_upload(local, "/tmp/archive.tar.gz")
    assert result.ok
    assert fake.uploads == [(str(local), "/tmp/archive.tar.gz")]


def test_key_only_keeps_batchmode(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    client = SSHClient(cfg)
    args = client._base_ssh_args()
    assert "BatchMode=yes" in " ".join(args)
    assert "SERVERBACKUP_ASKPASS" not in client.ssh_env()


def test_auth_failure_is_mapped():
    class AuthError(Exception):
        pass

    AuthError.__name__ = "AuthenticationException"
    cfg = AppConfig(ssh_username="zhzh", server_ip="192.168.18.18", ssh_private_key_path="")
    client = SSHClient(cfg, password="wrong-pass")
    mapped = client._map_paramiko_error(AuthError("Authentication failed."))
    assert "wrong username or password" in str(mapped)
    assert "zhzh@192.168.18.18" in str(mapped)
    assert "wrong-pass" not in str(mapped)


def test_sudo_askpass_keeps_json_stdin_separate(monkeypatch):
    class SudoFake(FakeParamiko):
        def __init__(self) -> None:
            super().__init__()
            self.last_stdin = ""
            self.helper_stdin = ""

        def exec_command(self, command, timeout=None):
            self.commands.append(command)
            stdout = b'{"ok":true,"hostname":"ubuntu"}' if "prepare-backup.sh" in command else b""

            class Chan:
                def recv_exit_status(self):
                    return 0

                def shutdown_write(self):
                    return None

            stdin = _FakeStdin(Chan())
            original = stdin.write

            def write(data: str) -> int:
                self.last_stdin = data
                if "prepare-backup.sh" in command:
                    self.helper_stdin = data
                return original(data)

            stdin.write = write  # type: ignore[method-assign]
            return stdin, _FakeStdout(stdout, Chan()), _FakeChannelFile(b"")

    fake = SudoFake()
    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: fake)
    cfg = AppConfig(
        ssh_username="zhzh",
        ssh_private_key_path="",
        remote_prepare_script="/usr/local/lib/serverbackup/prepare-backup.sh",
    )
    client = SSHClient(cfg, password="super-secret")
    result = client.run_script(cfg.remote_prepare_script, {"action": "check"})
    assert result.ok
    joined = " ".join(fake.commands)
    assert "super-secret" not in joined
    assert "sudo -A" in joined
    assert "SUDO_ASKPASS=" in joined
    assert "sudo -S" not in joined
    assert fake.helper_stdin.startswith("{")
    assert '"action":"check"' in fake.helper_stdin
    assert "super-secret" not in fake.helper_stdin
    client.close()
    assert fake.removed


def test_backup_now_stream_with_password_uses_paramiko_not_openssh(monkeypatch, tmp_path):
    fake = FakeParamiko()
    monkeypatch.setattr(SSHClient, "_connect_paramiko", lambda self: fake)

    def no_openssh_popen(*args, **kwargs):
        raise AssertionError(f"BACKUP NOW must not spawn OpenSSH: {args!r}")

    monkeypatch.setattr("app.ssh.client.subprocess.Popen", no_openssh_popen)
    cfg = AppConfig(
        ssh_username="zhzh",
        ssh_private_key_path="",
        remote_prepare_script="/usr/local/lib/serverbackup/prepare-backup.sh",
        backup_destination=str(tmp_path / "ServerBackups"),
        log_directory=str(tmp_path / "logs"),
        min_free_disk_gb=0.001,
        retry_count=1,
    )
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    Path(cfg.log_directory).mkdir(parents=True, exist_ok=True)
    client = SSHClient(cfg, password="super-secret")
    assert client.uses_paramiko() is True
    assert client.transport_name() == "paramiko"
    from app.engine.backup_engine import BackupEngine

    written = BackupEngine(cfg, ssh=client)._stream_backup(tmp_path / "archive.tar.gz")
    assert written == len(b"archive-bytes")
    joined = " ".join(fake.commands)
    assert "sudo -A" in joined
    assert "prepare-backup.sh" in joined
    assert "sudo -S" not in joined
    sent = getattr(fake, "sent", b"")
    assert b'"action":"backup"' in sent
    assert b"super-secret" not in sent
    fake.sent = b""
    client.popen_script(cfg.remote_prepare_script, {"action": "stream-objects", "files": [], "allowed_roots": []})
    sent = getattr(fake, "sent", b"")
    assert b'"action":"stream-objects"' in sent
    assert b"super-secret" not in sent


def test_key_only_popen_script_uses_openssh(monkeypatch):
    from io import BytesIO as _BytesIO

    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    captured: dict = {}

    class FakeProc:
        def __init__(self) -> None:
            self.stdin = _BytesIO()
            self.stdout = _BytesIO(b"archive-bytes")
            self.stderr = _BytesIO(b"")
            self.returncode = 0

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        return FakeProc()

    monkeypatch.setattr("app.ssh.client.subprocess.Popen", fake_popen)
    cfg = AppConfig(
        ssh_username="zhzh",
        ssh_private_key_path="",
        remote_prepare_script="/usr/local/lib/serverbackup/prepare-backup.sh",
    )
    client = SSHClient(cfg)
    assert client.uses_paramiko() is False
    assert client.transport_name() == "openssh"
    client.popen_script(cfg.remote_prepare_script, {"action": "backup"})
    assert captured["args"][0] == "/usr/bin/ssh"
    assert "BatchMode=yes" in captured["args"]


def test_gui_backup_now_passes_in_memory_password_to_same_ssh_client():
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parents[1] / "app" / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "SSHClient(config, password=password or None)" in source
    assert "mode=\"manual\"" in source or "mode='manual'" in source
    assert "ssh=self._ssh_client()" in source
    assert "engine.test_connection()" in source
    assert ".dry_run()" in source
    assert ".run()" in source


def test_bundled_ubuntu_scripts_exist():
    from app.ssh.client import UBUNTU_HELPER_FILES, bundled_ubuntu_scripts

    root = bundled_ubuntu_scripts()
    assert root.is_dir()
    for name in UBUNTU_HELPER_FILES:
        assert (root / name).is_file(), name
