"""SSH to Ubuntu. Password logins use Paramiko (Windows OpenSSH cannot type a password)."""

from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from app.config.schema import AppConfig
from app.security.allowlist import is_allowed_remote_action
from app.security.paths import validate_unix_path
from app.security.redact import redact_secrets

UBUNTU_HELPER_FILES = (
    "prepare-backup.sh",
    "prepare_backup.py",
    "prepare_master.py",
    "discover_apps.py",
    "discover_audit.py",
    "mysql_backup_user.py",
    "restore-backup.sh",
    "restore_backup.py",
    "restore_master.py",
    "security-audit.sh",
    "security_audit.py",
)
REMOTE_HELPER_DIR = "/usr/local/lib/serverbackup"
REMOTE_HELPER_STAGING = "/tmp/serverbackup-install"


def bundled_ubuntu_scripts() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "scripts" / "ubuntu"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / "scripts" / "ubuntu"


def unix_text_bytes(data: bytes) -> bytes:
    """Force LF endings so Windows-built helpers do not ship bash\\r shebangs."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


class SSHError(RuntimeError):
    pass


@dataclass
class SSHResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class _ParamikoProc:
    """Looks like subprocess.Popen enough for stream_copy."""

    def __init__(self, channel: Any) -> None:
        self._channel = channel
        self.stdout = channel.makefile("rb", 0)
        self.stderr = channel.makefile_stderr("rb", 0)
        self.returncode: int | None = None

    def wait(self) -> int:
        self.returncode = int(self._channel.recv_exit_status())
        return self.returncode

    def poll(self) -> int | None:
        if self._channel.exit_status_ready():
            return self.wait()
        return None

    def kill(self) -> None:
        try:
            self._channel.close()
        except Exception:
            return


class SSHClient:
    """Talk to Ubuntu using Paramiko for passwords, OpenSSH for key-only."""

    def __init__(
        self,
        config: AppConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        password: str | None = None,
    ) -> None:
        self.config = config
        self._runner = runner or subprocess.run
        self.password = password or None
        self._paramiko: Any = None
        self._sudo_askpass: str | None = None
        self._sudo_pwfile: str | None = None

    def _ssh_bin(self) -> str:
        found = shutil.which("ssh")
        if not found:
            raise SSHError("OpenSSH ssh client was not found on PATH.")
        return found

    def _key_path(self) -> Path | None:
        key = (self.config.ssh_private_key_path or "").strip()
        if not key:
            return None
        key_path = Path(os.path.expandvars(os.path.expanduser(key)))
        if not key_path.is_file():
            raise SSHError(f"SSH private key file not found: {key_path}")
        return key_path

    def _optional_key_path(self) -> Path | None:
        try:
            return self._key_path()
        except SSHError:
            return None

    def _use_password(self) -> bool:
        return bool(self.password)

    def uses_paramiko(self) -> bool:
        """Password logins use Paramiko. Key-only logins use OpenSSH BatchMode."""
        return self._use_password() and self._runner is subprocess.run

    def transport_name(self) -> str:
        return "paramiko" if self.uses_paramiko() else "openssh"

    def _base_ssh_args(self, binary: str | None = None) -> list[str]:
        args = [
            binary or self._ssh_bin(),
            "-p",
            str(self.config.ssh_port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={self.config.ssh_connect_timeout}",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
        ]
        key_path = self._key_path()
        if key_path:
            args.extend(["-i", str(key_path)])
        args.append(f"{self.config.ssh_username}@{self.config.server_ip}")
        return args

    def ssh_env(self) -> dict[str, str]:
        return os.environ.copy()

    def _popen_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"env": self.ssh_env()}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return kwargs

    def _map_paramiko_error(self, exc: BaseException) -> SSHError:
        name = type(exc).__name__
        text = str(exc).lower()
        if name == "AuthenticationException" or "authentication" in text:
            return SSHError(
                f"SSH login failed: wrong username or password for "
                f"{self.config.ssh_username}@{self.config.server_ip}. "
                "If Ubuntu only allows SSH keys, click Create SSH key instead of using a password."
            )
        if name in {"NoValidConnectionsError", "TimeoutError", "socket.timeout"} or isinstance(exc, (TimeoutError, OSError)):
            return SSHError(
                f"Cannot reach {self.config.server_ip} port {self.config.ssh_port}. "
                "Check that this Windows PC is on the same network and that SSH is running on Ubuntu."
            )
        return SSHError(f"SSH connection failed: {exc}")

    def _redact(self, text: str) -> str:
        redacted = redact_secrets(text or "")
        if self.password and self.password in redacted:
            redacted = redacted.replace(self.password, "[REDACTED]")
        return redacted

    @staticmethod
    def _sudo_password_required(result: SSHResult) -> bool:
        text = f"{result.stderr} {result.stdout}".lower()
        return any(
            token in text
            for token in (
                "password is required",
                "a terminal is required",
                "no tty present",
                "must have a tty",
            )
        )

    @staticmethod
    def _script_missing(result: SSHResult) -> bool:
        text = f"{result.stderr} {result.stdout}".lower()
        return any(
            token in text
            for token in (
                "no such file",
                "not found",
                "cannot execute",
                "can't open",
            )
        )

    def _sudo_argv(self, remote_command: list[str], *, feed_password: bool) -> list[str]:
        if feed_password:
            return ["sudo", "-S", "-p", "", *remote_command]
        return ["sudo", "-n", *remote_command]

    def _sudo_askpass_argv(self, remote_command: list[str]) -> list[str]:
        if not self._sudo_askpass:
            raise SSHError("sudo askpass helper is not prepared.")
        return [
            "env",
            f"SUDO_ASKPASS={self._sudo_askpass}",
            "sudo",
            "-A",
            "-p",
            "",
            *remote_command,
        ]

    def _write_remote_file(self, remote: str, data: bytes, mode: int) -> None:
        client = self._connect_paramiko()
        sftp = client.open_sftp()
        try:
            with sftp.open(remote, "wb") as handle:
                handle.write(data)
            sftp.chmod(remote, mode)
        finally:
            sftp.close()

    def _remove_remote_file(self, remote: str) -> None:
        try:
            client = self._connect_paramiko()
            sftp = client.open_sftp()
            try:
                sftp.remove(remote)
            finally:
                sftp.close()
        except Exception:
            return

    def _ensure_sudo_askpass(self) -> None:
        if self._sudo_askpass and self._sudo_pwfile:
            return
        if not self.password:
            raise SSHError("sudo password is not available")
        token = secrets.token_hex(8)
        pwfile = f"/tmp/serverbackup-sudo-{token}.pw"
        askpass = f"/tmp/serverbackup-sudo-{token}.askpass"
        self._write_remote_file(pwfile, (self.password + "\n").encode("utf-8"), 0o600)
        script = f"#!/bin/sh\nexec cat -- {shlex.quote(pwfile)}\n"
        self._write_remote_file(askpass, unix_text_bytes(script.encode("utf-8")), 0o700)
        self._sudo_pwfile = pwfile
        self._sudo_askpass = askpass

    def close(self) -> None:
        if self._sudo_pwfile:
            self._remove_remote_file(self._sudo_pwfile)
        if self._sudo_askpass:
            self._remove_remote_file(self._sudo_askpass)
        self._sudo_pwfile = None
        self._sudo_askpass = None
        if self._paramiko is not None:
            try:
                self._paramiko.close()
            except Exception:
                pass
            self._paramiko = None

    def _connect_paramiko(self) -> Any:
        if self._paramiko is not None:
            return self._paramiko
        try:
            import paramiko
        except ImportError as exc:
            raise SSHError(
                "Password login requires ServerBackup 1.3.1 or later (Paramiko is missing)."
            ) from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        key_path = self._optional_key_path()
        try:
            client.connect(
                hostname=self.config.server_ip,
                port=int(self.config.ssh_port),
                username=self.config.ssh_username,
                password=self.password,
                key_filename=str(key_path) if key_path else None,
                look_for_keys=False,
                allow_agent=False,
                timeout=self.config.ssh_connect_timeout,
                auth_timeout=self.config.ssh_connect_timeout,
                banner_timeout=self.config.ssh_connect_timeout,
            )
        except Exception as exc:
            raise self._map_paramiko_error(exc) from exc
        self._paramiko = client
        return client

    def _shell_join(self, remote_command: list[str]) -> str:
        return " ".join(shlex.quote(part) for part in remote_command)

    def run(
        self,
        remote_command: list[str],
        *,
        stdin_data: str | None = None,
        timeout: int | None = None,
        extra_ssh: list[str] | None = None,
    ) -> SSHResult:
        if not remote_command:
            raise SSHError("Remote command is empty.")
        if self.uses_paramiko():
            return self._run_paramiko(remote_command, stdin_data=stdin_data, timeout=timeout)
        args = self._base_ssh_args()
        if extra_ssh:
            host = args.pop()
            args.extend(extra_ssh)
            args.append(host)
        args.append("--")
        args.extend(remote_command)
        try:
            completed = self._runner(
                args,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout or self.config.ssh_connect_timeout,
                check=False,
                **self._popen_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise SSHError("SSH command timed out.") from exc
        except FileNotFoundError as exc:
            raise SSHError("OpenSSH ssh client was not found.") from exc
        except TypeError:
            completed = self._runner(
                args,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout or self.config.ssh_connect_timeout,
                check=False,
            )
        stdout = self._redact(completed.stdout or "")
        stderr = self._redact(completed.stderr or "")
        return SSHResult(completed.returncode, stdout, stderr)

    def _run_paramiko(
        self,
        remote_command: list[str],
        *,
        stdin_data: str | None,
        timeout: int | None,
    ) -> SSHResult:
        client = self._connect_paramiko()
        command = self._shell_join(remote_command)
        try:
            stdin, stdout, stderr = client.exec_command(
                command,
                timeout=timeout or self.config.ssh_connect_timeout,
            )
            if stdin_data:
                stdin.write(stdin_data)
                stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
        except SSHError:
            raise
        except Exception as extra:
            if isinstance(extra, TimeoutError) or type(extra).__name__ in {"timeout", "TimeoutError"}:
                raise SSHError("Ubuntu command timed out after SSH login succeeded.") from extra
            raise SSHError(f"SSH command failed: {extra}") from extra
        return SSHResult(code, self._redact(out), self._redact(err))

    def popen(self, remote_command: list[str], *, stdin_bytes: bytes | None = None) -> Any:
        if self.uses_paramiko():
            client = self._connect_paramiko()
            transport = client.get_transport()
            if transport is None:
                raise SSHError("SSH connection is not open.")
            channel = transport.open_session()
            channel.exec_command(self._shell_join(remote_command))
            if stdin_bytes:
                channel.sendall(stdin_bytes)
            channel.shutdown_write()
            return _ParamikoProc(channel)
        args = self._base_ssh_args()
        args.append("--")
        args.extend(remote_command)
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **self._popen_kwargs(),
        )
        if stdin_bytes is not None and process.stdin is not None:
            process.stdin.write(stdin_bytes)
            process.stdin.close()
        return process

    def scp_upload(self, local: Path, remote: str) -> SSHResult:
        if self.uses_paramiko():
            try:
                client = self._connect_paramiko()
                sftp = client.open_sftp()
                try:
                    sftp.put(str(local), remote)
                finally:
                    sftp.close()
            except SSHError:
                raise
            except Exception as extra:
                return SSHResult(1, "", self._redact(str(extra)))
            return SSHResult(0, "", "")
        scp = shutil.which("scp")
        if not scp:
            raise SSHError("OpenSSH scp client was not found on PATH.")
        args = [
            scp,
            "-P",
            str(self.config.ssh_port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
        ]
        key_path = self._key_path()
        if key_path:
            args.extend(["-i", str(key_path)])
        args.append(str(local))
        args.append(f"{self.config.ssh_username}@{self.config.server_ip}:{remote}")
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            **self._popen_kwargs(),
        )
        return SSHResult(
            completed.returncode,
            self._redact(completed.stdout or ""),
            self._redact(completed.stderr or ""),
        )

    def _upload_unix_text(self, local: Path, remote: str) -> SSHResult:
        data = unix_text_bytes(local.read_bytes())
        handle, tmp_name = tempfile.mkstemp(prefix="serverbackup-unix-")
        try:
            with os.fdopen(handle, "wb") as tmp:
                tmp.write(data)
            return self.scp_upload(Path(tmp_name), remote)
        finally:
            try:
                os.remove(tmp_name)
            except OSError:
                pass

    def _run_sudo(
        self,
        remote_command: list[str],
        *,
        stdin_data: str = "",
        timeout: int | None = None,
    ) -> SSHResult:
        if self.password:
            self._ensure_sudo_askpass()
            return self.run(
                self._sudo_askpass_argv(remote_command),
                stdin_data=stdin_data,
                timeout=timeout,
            )
        return self.run(
            self._sudo_argv(remote_command, feed_password=False),
            stdin_data=stdin_data,
            timeout=timeout,
        )

    def run_script(
        self,
        script_path: str,
        payload: Mapping[str, Any],
        *,
        timeout: int | None = None,
        use_sudo: bool = True,
    ) -> SSHResult:
        validate_unix_path(script_path, field="remote script")
        action = str(payload.get("action") or "")
        if not is_allowed_remote_action(action):
            raise SSHError(f"Remote action is not allowlisted: {action!r}")
        stdin_data = json.dumps(payload, separators=(",", ":"))
        if not use_sudo:
            return self.run([script_path], stdin_data=stdin_data, timeout=timeout)
        return self._run_sudo([script_path], stdin_data=stdin_data, timeout=timeout)

    def popen_script(self, script_path: str, payload: Mapping[str, Any]) -> Any:
        validate_unix_path(script_path, field="remote script")
        action = str(payload.get("action") or "")
        if not is_allowed_remote_action(action):
            raise SSHError(f"Remote action is not allowlisted: {action!r}")
        body = json.dumps(payload, separators=(",", ":"))
        if self.password:
            self._ensure_sudo_askpass()
            remote = self._sudo_askpass_argv([script_path])
        else:
            remote = self._sudo_argv([script_path], feed_password=False)
        return self.popen(remote, stdin_bytes=body.encode("utf-8"))

    def ensure_remote_scripts(self) -> SSHResult:
        source = bundled_ubuntu_scripts()
        missing = [name for name in UBUNTU_HELPER_FILES if not (source / name).is_file()]
        if missing:
            raise SSHError(f"Windows helper scripts are missing: {', '.join(missing)}")
        mkdir = self.run(["mkdir", "-p", REMOTE_HELPER_STAGING], timeout=self.config.ssh_connect_timeout)
        if not mkdir.ok:
            return SSHResult(mkdir.returncode, mkdir.stdout, mkdir.stderr or "Could not create /tmp staging directory.")
        for name in UBUNTU_HELPER_FILES:
            uploaded = self._upload_unix_text(source / name, f"{REMOTE_HELPER_STAGING}/{name}")
            if not uploaded.ok:
                return SSHResult(uploaded.returncode, uploaded.stdout, uploaded.stderr or f"Failed to upload {name}.")
        mkdir_dest = self._run_sudo(["mkdir", "-p", REMOTE_HELPER_DIR], timeout=60)
        if not mkdir_dest.ok:
            return SSHResult(
                mkdir_dest.returncode,
                mkdir_dest.stdout,
                mkdir_dest.stderr
                or "Could not create /usr/local/lib/serverbackup. SSH login is OK; sudo could not create the directory.",
            )
        for name in UBUNTU_HELPER_FILES:
            installed = self._run_sudo(
                [
                    "install",
                    "-m",
                    "0755",
                    f"{REMOTE_HELPER_STAGING}/{name}",
                    f"{REMOTE_HELPER_DIR}/{name}",
                ],
                timeout=60,
            )
            if not installed.ok:
                return SSHResult(
                    installed.returncode,
                    installed.stdout,
                    installed.stderr or f"Could not install {name} on Ubuntu.",
                )
        return SSHResult(0, "", "installed Ubuntu backup helpers")

    def test_login(self) -> SSHResult:
        return self.run(["printf", "ok"], timeout=self.config.ssh_connect_timeout)
