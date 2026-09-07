"""OpenSSH wrapper. Commands are argv lists; user data is JSON on stdin."""

from __future__ import annotations

import json
import os
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


class SSHClient:
    """Talk to Ubuntu using the system OpenSSH client (ssh/scp/sftp)."""

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
            "NumberOfPasswordPrompts=1",
        ]
        key_path = self._key_path()
        if self.password:
            args.extend(["-o", "BatchMode=no", "-o", "PreferredAuthentications=password,keyboard-interactive,publickey"])
        else:
            args.extend(["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"])
        if key_path:
            args.extend(["-o", "IdentitiesOnly=yes", "-i", str(key_path)])
        args.append(f"{self.config.ssh_username}@{self.config.server_ip}")
        return args

    def _askpass_helper(self) -> str:
        helper = Path(tempfile.gettempdir()) / "serverbackup-askpass.cmd"
        if getattr(sys, "frozen", False):
            line = f'@echo off\r\n"{sys.executable}" --askpass\r\n'
        else:
            line = f'@echo off\r\n"{sys.executable}" -m app.main --askpass\r\n'
        helper.write_text(line, encoding="utf-8")
        return str(helper)

    def ssh_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.password:
            env["SERVERBACKUP_ASKPASS"] = self.password
            env["SSH_ASKPASS"] = self._askpass_helper()
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env.setdefault("DISPLAY", ":0")
        return env

    def _popen_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"env": self.ssh_env()}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return kwargs

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
        args = self._base_ssh_args()
        if extra_ssh:
            # Insert extra options before the destination host.
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
            raise SSHError("SSH connection timed out.") from exc
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
        stdout = redact_secrets(completed.stdout or "")
        stderr = redact_secrets(completed.stderr or "")
        return SSHResult(completed.returncode, stdout, stderr)

    def popen(self, remote_command: list[str], *, stdin_bytes: bytes | None = None) -> subprocess.Popen[bytes]:
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
        scp = shutil.which("scp")
        if not scp:
            raise SSHError("OpenSSH scp client was not found on PATH.")
        args = [scp, "-P", str(self.config.ssh_port), "-o", "StrictHostKeyChecking=accept-new"]
        if self.password:
            args.extend(["-o", "BatchMode=no", "-o", "PreferredAuthentications=password,keyboard-interactive,publickey"])
        else:
            args.extend(["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"])
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
            redact_secrets(completed.stdout or ""),
            redact_secrets(completed.stderr or ""),
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
        remote = []
        if use_sudo:
            remote.extend(["sudo", "-n"])
        remote.append(script_path)
        stdin_data = json.dumps(payload, separators=(",", ":"))
        return self.run(remote, stdin_data=stdin_data, timeout=timeout)

    def test_login(self) -> SSHResult:
        return self.run(["printf", "ok"], timeout=self.config.ssh_connect_timeout)
