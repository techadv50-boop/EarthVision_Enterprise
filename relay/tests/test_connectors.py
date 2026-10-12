import stat
from datetime import datetime, timezone

import ftplib
import pytest

from relay.connectors import list_ftp_files, list_sftp_files, parse_mlsd_modify
from relay.remote import RemoteFile


def test_parse_mlsd_modify_is_utc() -> None:
    stamp = parse_mlsd_modify("20241012153045")
    expected = datetime(2024, 10, 12, 15, 30, 45, tzinfo=timezone.utc).timestamp()
    assert stamp == expected
    assert parse_mlsd_modify("20241012153045.500") == expected


class _Attr:
    def __init__(self, filename: str, mode: int, size: int = 0, mtime: float = 0) -> None:
        self.filename = filename
        self.st_mode = mode
        self.st_size = size
        self.st_mtime = mtime


class _Sftp:
    def __init__(self, tree: dict[str, list[_Attr]]) -> None:
        self.tree = tree

    def listdir_attr(self, path: str) -> list[_Attr]:
        return self.tree[path]


def test_sftp_listing_includes_nested_files_only() -> None:
    regular = stat.S_IFREG | 0o644
    directory = stat.S_IFDIR | 0o755
    link = stat.S_IFLNK | 0o777
    sftp = _Sftp(
        {
            "/drop": [
                _Attr("photo.jpg", regular, 12, 10),
                _Attr("album", directory),
                _Attr("skip-me", link),
            ],
            "/drop/album": [
                _Attr("a.zip", regular, 4, 11),
            ],
        }
    )
    found = list_sftp_files(sftp, "/drop")  # type: ignore[arg-type]
    assert found == [
        RemoteFile("photo.jpg", 12, 10),
        RemoteFile("album/a.zip", 4, 11),
    ]


class _Ftp:
    def __init__(self, files: dict[str, tuple[int, str]], *, mlsd: bool) -> None:
        self.files = files
        self.allow_mlsd = mlsd
        self.cwd_path = "/"
        self.dirs = _dirs(files)

    def mlsd(self, directory: str):
        if not self.allow_mlsd:
            raise ftplib.error_perm("500 MLSD not supported")
        return list(_children(self.files, self.dirs, directory).items())

    def pwd(self) -> str:
        return self.cwd_path

    def cwd(self, path: str) -> None:
        if path not in self.dirs:
            raise ftplib.error_perm("550 failed")
        self.cwd_path = path

    def nlst(self, directory: str) -> list[str]:
        children = _children(self.files, self.dirs, directory)
        return [f"{directory.rstrip('/')}/{name}" for name in children]

    def size(self, path: str) -> int:
        return self.files[path][0]

    def sendcmd(self, command: str) -> str:
        path = command.split(" ", 1)[1]
        return f"213 {self.files[path][1]}"


def _dirs(files: dict[str, tuple[int, str]]) -> set[str]:
    dirs = {"/"}
    for path in files:
        parts = [part for part in path.split("/") if part]
        built = ""
        for part in parts[:-1]:
            built += "/" + part
            dirs.add(built)
    return dirs


def _children(
    files: dict[str, tuple[int, str]],
    dirs: set[str],
    directory: str,
) -> dict[str, dict[str, str]]:
    prefix = directory.rstrip("/")
    children: dict[str, dict[str, str]] = {}
    for path, (size, modified) in files.items():
        if not path.startswith(prefix + "/"):
            continue
        rest = path[len(prefix) + 1 :]
        name = rest.split("/", 1)[0]
        if "/" in rest:
            children[name] = {"type": "dir"}
        else:
            children[name] = {"type": "file", "size": str(size), "modify": modified}
    for path in dirs:
        if path.startswith(prefix + "/"):
            rest = path[len(prefix) + 1 :]
            if "/" not in rest and rest not in children:
                children[rest] = {"type": "dir"}
    return children


@pytest.mark.parametrize("use_mlsd", [True, False])
def test_ftp_listing_walks_subfolders(use_mlsd: bool) -> None:
    ftp = _Ftp(
        {
            "/drop/photo.jpg": (12, "20241012120000"),
            "/drop/album/a.zip": (4, "20241012120100"),
        },
        mlsd=use_mlsd,
    )
    found = list_ftp_files(ftp, "/drop")  # type: ignore[arg-type]
    by_path = {item.relative_path: item for item in found}
    assert set(by_path) == {"photo.jpg", "album/a.zip"}
    assert by_path["photo.jpg"].size == 12
    assert by_path["album/a.zip"].mtime == parse_mlsd_modify("20241012120100")
