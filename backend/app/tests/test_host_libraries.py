"""Host extras library install (no image rebuild)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import host_libraries as hl


@pytest.fixture()
def extras_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "python_extras"
    root.mkdir()
    monkeypatch.setenv("EV_PYTHON_EXTRAS_DIR", str(root))
    # Reset any prior path pollution carefully
    hl.ensure_extras_on_sys_path()
    return root


def test_list_installed_empty(extras_tmp: Path):
    doc = hl.list_installed()
    assert doc["ok"] is True
    assert doc["extras_dir"] == str(extras_tmp)
    assert doc["packages"] == {}


def test_reject_bad_extension(extras_tmp: Path):
    with pytest.raises(hl.HostLibraryError, match="unsupported"):
        hl.install_wheels(files=[("evil.exe", b"1234567890" * 10)], actor="test")


def test_pip_index_disabled_by_default(extras_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EV_HOST_LIBS_ALLOW_PIP", raising=False)
    with pytest.raises(hl.HostLibraryError, match="PyPI install disabled"):
        hl.install_from_index(package="spectral", version=None, actor="test")
