from io import BytesIO

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

        class SFTP:
            def put(self, local, remote):
                client.uploads.append((local, remote))

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


def test_sudo_uses_password_on_stdin_not_argv(monkeypatch):
    class SudoFake(FakeParamiko):
        def exec_command(self, command, timeout=None):
            self.commands.append(command)
            needs_n = " -n " in f" {command} "
            code = 1 if needs_n else 0
            stderr = b"sudo: a password is required\n" if needs_n else b""
            stdout = b"" if needs_n else b'{"ok":true}'

            class Chan:
                def recv_exit_status(self):
                    return code

                def shutdown_write(self):
                    return None

            stdin = _FakeStdin(Chan())
            original = stdin.write

            def write(data: str) -> int:
                self.last_stdin = data
                return original(data)

            stdin.write = write  # type: ignore[method-assign]
            return stdin, _FakeStdout(stdout, Chan()), _FakeChannelFile(stderr)

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
    assert "sudo -S" in joined
    assert getattr(fake, "last_stdin", "").startswith("super-secret\n")
    assert '"action":"check"' in fake.last_stdin
    assert client._sudo_needs_password is True


def test_bundled_ubuntu_scripts_exist():
    from app.ssh.client import UBUNTU_HELPER_FILES, bundled_ubuntu_scripts

    root = bundled_ubuntu_scripts()
    assert root.is_dir()
    for name in UBUNTU_HELPER_FILES:
        assert (root / name).is_file(), name
