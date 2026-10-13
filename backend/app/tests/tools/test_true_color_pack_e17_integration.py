"""E1.7 — production-integration paths, signatures, install≠activate, persistence."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.tools.pack_loader import PackIntegrityError, verify_pack
from app.tools.pack_ops import (
    PackOpsError,
    activate_pack,
    ensure_default_pins,
    install_pack_from_dir,
    rollback_pack,
)
from app.tools.pack_paths import artifacts_root, pins_path
from app.tools.pack_signatures import (
    PackSignatureError,
    generate_keypair,
    sign_digest,
    verify_digest_signature,
    write_signature_file,
)
from app.tools.runtime_pins import get_pin

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture()
def pack_volume(tmp_path, monkeypatch):
    root = tmp_path / "tool_packs"
    arts = root / "artifacts"
    arts.mkdir(parents=True)
    pins = root / "runtime_pins.json"
    pubs = root / "publishers"
    pubs.mkdir()
    priv, pub = generate_keypair()
    (pubs / "approved_publishers.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "publishers": [
                    {
                        "id": "test-pub",
                        "name": "Test",
                        "enabled": True,
                        "public_key": pub,
                    }
                ],
            }
        )
        + "\n"
    )
    monkeypatch.setenv("EV_TOOL_PACKS_ROOT", str(root))
    monkeypatch.setenv("EV_RUNTIME_PINS", str(pins))
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(arts))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(pubs / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    # Ephemeral test publisher is production-profile-safe (not preview-dev)
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_AUDIT_LOG", str(root / "audit" / "promotions.jsonl"))
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    ensure_default_pins()
    yield {
        "root": root,
        "priv": priv,
        "pub": pub,
        "arts": arts,
        "pins": pins,
    }
    rp._CACHE = {"mtime": None, "data": None}


def _signed_source(tmp_path: Path, version: str, priv: str, publisher_id: str = "test-pub") -> Path:
    src_repo = REPO / "tools" / "artifacts" / "true_color" / version
    dest = tmp_path / f"src-{version}"
    shutil.copytree(src_repo, dest)
    # Re-sign with test publisher (repo signatures use preview-dev key)
    # Point verify at dest via temporary EV_ARTIFACTS_ROOT sibling layout
    layout = tmp_path / f"layout-{version}"
    pack = layout / "true_color" / version
    if pack.exists():
        shutil.rmtree(pack)
    shutil.copytree(dest, pack)
    prev = os.environ.get("EV_ARTIFACTS_ROOT")
    os.environ["EV_ARTIFACTS_ROOT"] = str(layout)
    try:
        meta = verify_pack("true_color", version)
    finally:
        if prev is None:
            os.environ.pop("EV_ARTIFACTS_ROOT", None)
        else:
            os.environ["EV_ARTIFACTS_ROOT"] = prev
    sig = sign_digest(meta["digest"], priv)
    write_signature_file(dest, digest=meta["digest"], signature=sig, publisher_id=publisher_id)
    return dest


def test_ev_paths_inside_volume_layout(pack_volume):
    assert pins_path() == pack_volume["pins"]
    assert artifacts_root() == pack_volume["arts"]
    pin = get_pin("true_color")
    assert pin["mode"] == "builtin"


def test_install_does_not_activate(pack_volume, tmp_path):
    src = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    install_pack_from_dir(
        src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
    )
    assert (pack_volume["arts"] / "true_color" / "1.0.0" / "pack.json").is_file()
    assert get_pin("true_color")["mode"] == "builtin"


def test_activate_requires_confirm_and_signature(pack_volume, tmp_path):
    src = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    install_pack_from_dir(
        src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
    )
    with pytest.raises(PackOpsError, match="confirm"):
        activate_pack(tool_id="true_color", version="1.0.0", actor="tester", confirm="yes")
    activate_pack(tool_id="true_color", version="1.0.0", actor="tester", confirm="activate")
    pin = get_pin("true_color")
    assert pin["mode"] == "pack"
    assert pin["version"] == "1.0.0"


def test_unsigned_rejected_when_required(pack_volume, tmp_path):
    src_repo = REPO / "tools" / "artifacts" / "true_color" / "1.0.0"
    dest = tmp_path / "unsigned"
    shutil.copytree(src_repo, dest)
    (dest / "SIGNATURE.json").unlink(missing_ok=True)
    with pytest.raises(PackOpsError):
        install_pack_from_dir(
            dest, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
        )


def test_immutable_reinstall_rejected(pack_volume, tmp_path):
    src = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    install_pack_from_dir(
        src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
    )
    with pytest.raises(PackOpsError, match="immutable"):
        install_pack_from_dir(
            src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
        )


def test_promote_rollback_and_audit(pack_volume, tmp_path):
    s0 = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    s1 = _signed_source(tmp_path, "1.1.0", pack_volume["priv"])
    install_pack_from_dir(
        s0, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
    )
    install_pack_from_dir(
        s1, tool_id="true_color", version="1.1.0", actor="tester", confirm="install"
    )
    activate_pack(tool_id="true_color", version="1.0.0", actor="tester", confirm="activate")
    activate_pack(tool_id="true_color", version="1.1.0", actor="tester", confirm="activate")
    assert get_pin("true_color")["version"] == "1.1.0"
    rollback_pack(tool_id="true_color", to="1.0.0", actor="tester", confirm="rollback")
    assert get_pin("true_color")["version"] == "1.0.0"
    rollback_pack(tool_id="true_color", to="builtin", actor="tester", confirm="rollback")
    assert get_pin("true_color")["mode"] == "builtin"
    audit = (pack_volume["root"] / "audit" / "promotions.jsonl").read_text()
    assert "activate" in audit and "rollback" in audit


def test_persistence_survives_new_process_env(pack_volume, tmp_path):
    """Simulates container restart: same volume paths, fresh pin cache."""
    src = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    install_pack_from_dir(
        src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
    )
    activate_pack(tool_id="true_color", version="1.0.0", actor="tester", confirm="activate")
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    assert get_pin("true_color")["version"] == "1.0.0"
    assert (pack_volume["arts"] / "true_color" / "1.0.0" / "backend" / "plugin.py").is_file()


def test_wrong_publisher_signature_rejected(pack_volume, tmp_path):
    src = _signed_source(tmp_path, "1.0.0", pack_volume["priv"])
    other_priv, _other_pub = generate_keypair()
    # overwrite signature with unauthorized key
    layout = tmp_path / "reverify"
    pack = layout / "true_color" / "1.0.0"
    shutil.copytree(src, pack)
    prev = os.environ.get("EV_ARTIFACTS_ROOT")
    os.environ["EV_ARTIFACTS_ROOT"] = str(layout)
    try:
        meta = verify_pack("true_color", "1.0.0")
    finally:
        if prev is None:
            os.environ.pop("EV_ARTIFACTS_ROOT", None)
        else:
            os.environ["EV_ARTIFACTS_ROOT"] = prev
    bad_sig = sign_digest(meta["digest"], other_priv)
    write_signature_file(src, digest=meta["digest"], signature=bad_sig, publisher_id="test-pub")
    with pytest.raises(PackOpsError):
        install_pack_from_dir(
            src, tool_id="true_color", version="1.0.0", actor="tester", confirm="install"
        )
