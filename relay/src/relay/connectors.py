"""SFTP and FTPS access. Plain FTP is intentionally unsupported."""

from __future__ import annotations

import ftplib
import logging
import posixpath
import stat
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from relay.config import Endpoint
from relay.paths import prepare_local_download
from relay.remote import RemoteFile

logger = logging.getLogger(__name__)

_CHUNK = 256 * 1024


class ConnectorError(OSError):
    """A remote listing or transfer failed."""


def connect(endpoint: Endpoint) -> SftpConnector | FtpsConnector:
    if endpoint.protocol == "sftp":
        return SftpConnector(endpoint)
    if endpoint.protocol == "ftps":
        return FtpsConnector(endpoint)
    raise ConnectorError(f"protocol {endpoint.protocol} is not supported")


def parse_mlsd_modify(value: str | None) -> float:
    """Turn an MLSD or MDTM timestamp into a UTC unix time."""
    if not value:
        return 0.0
    stamp = value.strip().split(".", 1)[0]
    try:
        parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ConnectorError(f"unreadable modification time {value!r}") from exc
    return parsed.timestamp()


def list_sftp_files(sftp: paramiko.SFTPClient, remote_dir: str) -> list[RemoteFile]:
    found: list[RemoteFile] = []
    _walk_sftp(sftp, remote_dir.rstrip("/"), "", found)
    return found


def list_ftp_files(ftp: ftplib.FTP, remote_dir: str) -> list[RemoteFile]:
    found: list[RemoteFile] = []
    root = remote_dir.rstrip("/")
    try:
        _walk_mlsd(ftp, root, "", found)
    except ftplib.error_perm as exc:
        if found:
            raise ConnectorError(f"listing {root} failed after a partial MLSD") from exc
        _walk_nlst(ftp, root, "", found)
    return found


class SftpConnector:
    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def __enter__(self) -> SftpConnector:
        client = paramiko.SSHClient()
        try:
            if self.endpoint.known_hosts_path and Path(self.endpoint.known_hosts_path).exists():
                client.load_host_keys(self.endpoint.known_hosts_path)
            else:
                client.load_system_host_keys()
            if self.endpoint.host_key_policy == "accept-new":
                client.set_missing_host_key_policy(
                    _AcceptNewPolicy(self.endpoint.known_hosts_path)
                )
            else:
                client.set_missing_host_key_policy(paramiko.RejectPolicy())

            pkey = None
            if self.endpoint.private_key_path:
                pkey = _load_private_key(
                    self.endpoint.private_key_path,
                    self.endpoint.private_key_passphrase,
                )
            client.connect(
                hostname=self.endpoint.host,
                port=self.endpoint.port,
                username=self.endpoint.username,
                password=self.endpoint.password,
                pkey=pkey,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(30)
            self._client = client
            self._sftp = client.open_sftp()
        except Exception:
            client.close()
            self._client = None
            self._sftp = None
            raise
        return self

    def __exit__(self, *args: object) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    def list_files(self, remote_dir: str) -> list[RemoteFile]:
        return list_sftp_files(self._require(), remote_dir)

    def download(self, remote_path: str, local_path: Path, expected_size: int) -> None:
        offset = prepare_local_download(local_path, expected_size)
        if offset is None:
            return
        sftp = self._require()
        with sftp.open(remote_path, "rb") as src, open(local_path, "ab" if offset else "wb") as dst:
            if offset:
                src.seek(offset)
            _copy_fileobj(src, dst)

    def upload(self, local_path: Path, remote_path: str) -> None:
        sftp = self._require()
        parent = posixpath.dirname(remote_path)
        _mkdir_p_sftp(sftp, parent)
        sftp.put(str(local_path), remote_path, confirm=True)

    def _require(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            raise ConnectorError("SFTP session is not open")
        return self._sftp


class _SessionReuseFTP_TLS(ftplib.FTP_TLS):
    """Reuse the TLS session on the data connection.

    Shared-hosting FTPS servers reject a data connection that starts a new
    TLS session. The standard library does that unless this is overridden.
    """

    def ntransfercmd(self, cmd: str, rest: int | str | None = None) -> tuple:
        connection, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            connection = self.context.wrap_socket(
                connection,
                server_hostname=self.host,
                session=self.sock.session,  # type: ignore[union-attr]
            )
        return connection, size


class FtpsConnector:
    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint
        self._ftp: _SessionReuseFTP_TLS | None = None

    def __enter__(self) -> FtpsConnector:
        ftp = _SessionReuseFTP_TLS()
        ftp.encoding = "utf-8"
        ftp.connect(self.endpoint.host, self.endpoint.port, timeout=30)
        ftp.login(self.endpoint.username, self.endpoint.password or "")
        ftp.prot_p()
        ftp.set_pasv(True)
        self._ftp = ftp
        return self

    def __exit__(self, *args: object) -> None:
        if self._ftp is None:
            return
        try:
            self._ftp.quit()
        except Exception:
            self._ftp.close()
        self._ftp = None

    def list_files(self, remote_dir: str) -> list[RemoteFile]:
        return list_ftp_files(self._require(), remote_dir)

    def download(self, remote_path: str, local_path: Path, expected_size: int) -> None:
        offset = prepare_local_download(local_path, expected_size)
        if offset is None:
            return
        ftp = self._require()
        with open(local_path, "ab" if offset else "wb") as dst:
            ftp.retrbinary(
                f"RETR {remote_path}",
                dst.write,
                blocksize=_CHUNK,
                rest=offset or None,
            )

    def upload(self, local_path: Path, remote_path: str) -> None:
        ftp = self._require()
        parent = posixpath.dirname(remote_path)
        _mkdir_p_ftp(ftp, parent)
        with open(local_path, "rb") as src:
            ftp.storbinary(f"STOR {remote_path}", src, blocksize=_CHUNK)

    def _require(self) -> _SessionReuseFTP_TLS:
        if self._ftp is None:
            raise ConnectorError("FTPS session is not open")
        return self._ftp


class _AcceptNewPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, known_hosts_path: str | None) -> None:
        self.known_hosts_path = known_hosts_path

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        client.get_host_keys().add(hostname, key.get_name(), key)
        if self.known_hosts_path:
            path = Path(self.known_hosts_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(path))
        logger.warning("stored new SSH host key for %s", hostname)


def _load_private_key(path: str, passphrase: str | None) -> paramiko.PKey:
    errors: list[str] = []
    for loader in (
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.RSAKey,
    ):
        try:
            return loader.from_private_key_file(path, password=passphrase)
        except (paramiko.SSHException, OSError) as exc:
            errors.append(str(exc))
    raise ConnectorError(f"could not read private key {path}: {errors[-1] if errors else 'unknown'}")


def _walk_sftp(
    sftp: paramiko.SFTPClient,
    directory: str,
    prefix: str,
    found: list[RemoteFile],
) -> None:
    for attr in sftp.listdir_attr(directory):
        name = attr.filename
        if name in (".", ".."):
            continue
        relative = name if not prefix else f"{prefix}/{name}"
        full = f"{directory}/{name}"
        mode = attr.st_mode or 0
        if stat.S_ISDIR(mode):
            _walk_sftp(sftp, full, relative, found)
        elif stat.S_ISREG(mode):
            found.append(
                RemoteFile(
                    relative_path=relative,
                    size=int(attr.st_size or 0),
                    mtime=float(attr.st_mtime or 0),
                )
            )


def _walk_mlsd(
    ftp: ftplib.FTP,
    directory: str,
    prefix: str,
    found: list[RemoteFile],
) -> None:
    for name, facts in ftp.mlsd(directory):
        if name in (".", ".."):
            continue
        relative = name if not prefix else f"{prefix}/{name}"
        full = f"{directory}/{name}"
        kind = facts.get("type", "")
        if kind == "dir":
            _walk_mlsd(ftp, full, relative, found)
        elif kind == "file":
            found.append(
                RemoteFile(
                    relative_path=relative,
                    size=int(facts.get("size") or 0),
                    mtime=parse_mlsd_modify(facts.get("modify")),
                )
            )


def _walk_nlst(
    ftp: ftplib.FTP,
    directory: str,
    prefix: str,
    found: list[RemoteFile],
) -> None:
    current = ftp.pwd()
    try:
        names = ftp.nlst(directory)
    finally:
        ftp.cwd(current)
    for raw in names:
        candidate = raw.rstrip("/")
        name = posixpath.basename(candidate)
        if name in (".", "..") or candidate == directory:
            continue
        full = f"{directory}/{name}"
        relative = name if not prefix else f"{prefix}/{name}"
        if _ftp_is_dir(ftp, full):
            _walk_nlst(ftp, full, relative, found)
            continue
        size = int(ftp.size(full) or 0)
        response = ftp.sendcmd(f"MDTM {full}")
        stamp = response.split()[-1] if response else ""
        found.append(
            RemoteFile(
                relative_path=relative,
                size=size,
                mtime=parse_mlsd_modify(stamp),
            )
        )


def _ftp_is_dir(ftp: ftplib.FTP, path: str) -> bool:
    current = ftp.pwd()
    is_dir = False
    try:
        ftp.cwd(path)
        is_dir = True
    except ftplib.error_perm:
        is_dir = False
    try:
        ftp.cwd(current)
    except ftplib.error_perm:
        logger.warning("could not return to FTP directory %s", current)
    return is_dir


def _mkdir_p_sftp(sftp: paramiko.SFTPClient, directory: str) -> None:
    directory = directory.rstrip("/")
    if not directory:
        return
    absolute = directory.startswith("/")
    built: list[str] = []
    for part in [part for part in directory.split("/") if part]:
        built.append(part)
        path = ("/" if absolute else "") + "/".join(built)
        try:
            sftp.stat(path)
        except OSError:
            sftp.mkdir(path)


def _mkdir_p_ftp(ftp: ftplib.FTP, directory: str) -> None:
    directory = directory.rstrip("/")
    if not directory:
        return
    absolute = directory.startswith("/")
    built: list[str] = []
    for part in [part for part in directory.split("/") if part]:
        built.append(part)
        path = ("/" if absolute else "") + "/".join(built)
        try:
            ftp.mkd(path)
        except ftplib.error_perm as exc:
            # 550 is "already exists" on the servers this fallback targets.
            if not str(exc).startswith("550"):
                raise


def _copy_fileobj(src: object, dst: object) -> None:
    read = getattr(src, "read")
    write = getattr(dst, "write")
    while True:
        block = read(_CHUNK)
        if not block:
            return
        write(block)
