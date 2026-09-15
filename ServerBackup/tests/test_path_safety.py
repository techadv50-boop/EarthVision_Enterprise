from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.security.paths import contained_in_unix_root, is_safe_unix_path, validate_unix_path
from tests.helpers import UBUNTU_SCRIPTS

PRODUCTION_JPG = (
    "publication-fee-by-coorsponding-author-a-survey-paper-on-ascii-based-cryptographic-techniques..jpg"
)
PRODUCTION_PATH = (
    "/var/www/journal.50sea.com/public/site/images/abidsultan006/" + PRODUCTION_JPG
)


def _pm():
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import path_safety
    import prepare_master as pm

    return pm, path_safety


def test_production_jpg_filename_is_not_treated_as_traversal():
    pm, path_safety = _pm()
    assert ".." in PRODUCTION_JPG
    assert path_safety.require_unix_syntax(PRODUCTION_PATH) == PRODUCTION_PATH
    assert path_safety.contained_in_root(
        PRODUCTION_PATH, "/var/www/journal.50sea.com", follow_symlinks=False
    )
    assert path_safety.has_traversal_component(PRODUCTION_PATH) is False
    assert path_safety.has_traversal_component("/var/www/../../etc/passwd") is True
    assert is_safe_unix_path(PRODUCTION_PATH) is True
    assert is_safe_unix_path("/var/www/../../etc/passwd") is False
    assert pm.safe_unix(PRODUCTION_PATH) == PRODUCTION_PATH


def test_inventory_hash_and_stream_accept_the_failing_ojs_jpg(tmp_path: Path):
    pm, _path_safety = _pm()
    root = tmp_path / "var/www/journal.50sea.com"
    dest = root / "public/site/images/abidsultan006"
    dest.mkdir(parents=True)
    target = dest / PRODUCTION_JPG
    target.write_bytes(b"jpeg-bytes")
    result = pm.inventory({"sources": [{"root": str(root), "category": "website"}]})
    assert result["ok"] is True
    abs_paths = [item["absolute_path"] for item in result["files"]]
    assert str(target) in abs_paths
    hashed = pm.hash_files({"paths": [str(target)], "allowed_roots": [str(root)]})
    assert hashed["ok"] is True
    assert hashed["hashes"]


def test_long_hyphen_space_unicode_and_nested_names(tmp_path: Path):
    pm, path_safety = _pm()
    root = tmp_path / "var/www/journal.50sea.com"
    nested = root / "public" / "site" / "images" / "author name"
    nested.mkdir(parents=True)
    names = [
        "normal-file.jpg",
        "file with spaces.pdf",
        "naïve-unicode.docx",
        "a" * 180 + ".zip",
        "techniques..jpg",
    ]
    for name in names:
        (nested / name).write_text("ok", encoding="utf-8")
    result = pm.inventory({"sources": [{"root": str(root), "category": "website"}]})
    assert result["ok"] is True
    found = {Path(item["absolute_path"]).name for item in result["files"]}
    for name in names:
        assert name in found
        assert path_safety.require_unix_syntax(str(nested / name))


def test_traversal_and_absolute_injection_are_rejected(tmp_path: Path):
    pm, path_safety = _pm()
    root = tmp_path / "var/www/journal.50sea.com"
    root.mkdir(parents=True)
    (root / "ok.txt").write_text("in", encoding="utf-8")
    outside = tmp_path / "etc" / "passwd"
    outside.parent.mkdir(parents=True)
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(SystemExit):
        pm.safe_unix("/var/www; rm -rf /")
    hashed = pm.hash_files({"paths": [str(outside)], "allowed_roots": [str(root)]})
    assert hashed["ok"] is False
    assert any("not under approved source" in err or "escapes" in err for err in hashed["errors"])
    assert path_safety.contained_in_root(str(outside), str(root)) is False
    assert path_safety.contained_in_root(
        str(root / "ok.txt" / ".." / ".." / "etc" / "passwd"),
        str(root),
        follow_symlinks=False,
    ) is False


def test_symlink_inside_root_is_allowed_escape_is_reported(tmp_path: Path):
    pm, path_safety = _pm()
    root = tmp_path / "var/www/journal.50sea.com"
    inside = root / "files"
    inside.mkdir(parents=True)
    target = inside / "kept.bin"
    target.write_bytes(b"data")
    good_link = inside / "alias.bin"
    good_link.symlink_to(target)
    outside = tmp_path / "secret.bin"
    outside.write_bytes(b"secret")
    bad_link = inside / "escape.bin"
    bad_link.symlink_to(outside)
    result = pm.inventory({"sources": [{"root": str(root), "category": "website"}]})
    names = {Path(item["absolute_path"]).name for item in result["files"]}
    assert "kept.bin" in names
    assert "alias.bin" in names
    assert "escape.bin" not in names
    assert result["ok"] is False
    assert any("symlink escapes approved root" in err for err in result["errors"])
    assert path_safety.symlink_escapes_root(str(bad_link), str(root)) is True
    assert path_safety.symlink_escapes_root(str(good_link), str(root)) is False
    hashed = pm.hash_files({"paths": [str(good_link)], "allowed_roots": [str(root)]})
    assert hashed["ok"] is True
    hashed_bad = pm.hash_files({"paths": [str(bad_link)], "allowed_roots": [str(root)]})
    assert hashed_bad["ok"] is False


def test_windows_validator_accepts_dots_in_filename():
    validate_unix_path(PRODUCTION_PATH, field="file")
    assert contained_in_unix_root(
        PRODUCTION_PATH, "/var/www/journal.50sea.com", follow_symlinks=False
    )
    assert not is_safe_unix_path("/var/www/foo/../../../etc/passwd")
    assert not is_safe_unix_path("/etc/passwd;id")
