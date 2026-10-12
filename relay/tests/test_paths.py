from pathlib import Path

import pytest

from relay.paths import (
    PathError,
    check_relative,
    local_path_for,
    prepare_local_download,
    remote_join,
)


def test_remote_join_keeps_files_inside_the_drop_folder() -> None:
    assert remote_join("/home/user/drop", "album/a.zip") == "/home/user/drop/album/a.zip"
    with pytest.raises(PathError):
        remote_join("/home/user/drop", "../secret")
    with pytest.raises(PathError):
        remote_join("/home/user/drop", "/etc/passwd")
    with pytest.raises(PathError):
        check_relative("a//b")


def test_local_path_stays_in_staging(tmp_path: Path) -> None:
    path = local_path_for(tmp_path, "namecheap", "album/a.zip")
    assert path == (tmp_path / "namecheap" / "album" / "a.zip").resolve()
    with pytest.raises(PathError):
        local_path_for(tmp_path, "namecheap", "../outside")


def test_prepare_local_download_resumes_or_restarts(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    assert prepare_local_download(target, 5) == 0
    target.write_bytes(b"ab")
    assert prepare_local_download(target, 5) == 2
    target.write_bytes(b"abcde")
    assert prepare_local_download(target, 5) is None
    target.write_bytes(b"abcdef")
    assert prepare_local_download(target, 5) == 0
    assert not target.exists()
