"""Stage P1 — Plugin Manager foundation tests."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.plugins import engine
from app.plugins.permissions import FORBIDDEN_PERMISSIONS, validate_permissions
from app.plugins.registry import (
    PluginRegistryError,
    get_plugin,
    load_registry,
    validate_plugin_id,
)
from app.plugins.slots import SUPPORTED_SLOTS, validate_slot
from app.tools.pack_loader import verify_pack
from app.tools.pack_ops import PackOpsError, ensure_default_pins
from app.tools.pack_signatures import generate_keypair, sign_digest, write_signature_file
from app.tools.runtime_pins import get_pin

REPO = Path(__file__).resolve().parents[4]
DEMO_ART = REPO / "tools" / "plugins" / "demo_hello" / "artifacts"


@pytest.fixture()
def plugin_volume(tmp_path, monkeypatch):
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
                        "environment": "production",
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
    monkeypatch.setenv("EV_PLUGIN_REGISTRY", str(root / "plugin_registry.json"))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(pubs / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_AUDIT_LOG", str(root / "audit" / "promotions.jsonl"))
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    ensure_default_pins()
    load_registry(force=True)
    yield {"root": root, "priv": priv, "arts": arts, "pins": pins}
    rp._CACHE = {"mtime": None, "data": None}


def _signed_demo(tmp_path: Path, version: str, priv: str) -> Path:
    src_repo = DEMO_ART / version
    if not (src_repo / "pack.json").is_file():
        pytest.skip(f"demo_hello@{version} artifact missing")
    dest = tmp_path / f"demo-{version}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_repo, dest)
    layout = tmp_path / f"layout-{version}"
    pack = layout / "demo_hello" / version
    shutil.copytree(dest, pack)
    prev = os.environ.get("EV_ARTIFACTS_ROOT")
    os.environ["EV_ARTIFACTS_ROOT"] = str(layout)
    try:
        meta = verify_pack("demo_hello", version)
    finally:
        if prev is None:
            os.environ.pop("EV_ARTIFACTS_ROOT", None)
        else:
            os.environ["EV_ARTIFACTS_ROOT"] = prev
    sig = sign_digest(meta["digest"], priv)
    write_signature_file(dest, digest=meta["digest"], signature=sig, publisher_id="test-pub")
    return dest


def test_supported_slots():
    assert "left_toolbar" in SUPPORTED_SLOTS
    assert "right_analysis_panel" in SUPPORTED_SLOTS
    assert "map_overlay" in SUPPORTED_SLOTS
    assert "results_panel" in SUPPORTED_SLOTS
    with pytest.raises(ValueError, match="invalid UI slot"):
        validate_slot("evil_slot")


def test_permission_validation():
    assert validate_permissions(["synthetic_data"]) == ["synthetic_data"]
    for bad in FORBIDDEN_PERMISSIONS:
        with pytest.raises(ValueError):
            validate_permissions([bad])
    with pytest.raises(ValueError):
        validate_permissions(["not_a_real_perm"])


def test_plugin_id_rejects_legacy():
    with pytest.raises(PluginRegistryError, match="frozen legacy"):
        validate_plugin_id("true_color")
    with pytest.raises(PluginRegistryError, match="frozen legacy"):
        validate_plugin_id("ship_detection")
    with pytest.raises(PluginRegistryError):
        validate_plugin_id("Bad-ID")


def test_invalid_signature_rejected(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    # Tamper signature
    sig_path = src / "SIGNATURE.json"
    data = json.loads(sig_path.read_text())
    data["signature"] = "AAAA"
    sig_path.write_text(json.dumps(data))
    with pytest.raises(PackOpsError):
        engine.validate_plugin_package(src)


def test_incompatible_host_api(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    meta = json.loads((src / "pack.json").read_text())
    meta["host_sdk"] = ">=99.0.0"
    (src / "pack.json").write_text(json.dumps(meta, indent=2) + "\n")
    # Re-sign would fail digest anyway; validate catches host_sdk before or after
    with pytest.raises(PackOpsError, match="incompatible"):
        engine.validate_plugin_package(src)


def test_invalid_slot_in_meta(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    ui = json.loads((src / "ui" / "tool-meta.json").read_text())
    ui["frontend_slot"] = "not_a_slot"
    (src / "ui" / "tool-meta.json").write_text(json.dumps(ui, indent=2) + "\n")
    with pytest.raises(PackOpsError, match="invalid UI slot"):
        engine.validate_plugin_package(src)


def test_install_inactive_activate_disable_rollback(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.validate_plugin_package(src)
    engine.register_from_validation(engine.validate_plugin_package(src))
    rec = get_plugin("demo_hello")
    assert rec["activation_status"] == "inactive"
    assert rec["installation_status"] == "not_installed"

    installed = engine.install_plugin_from_dir(
        src, plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="install"
    )
    assert installed["ok"] is True
    assert installed["activation_status"] == "inactive"
    assert get_plugin("demo_hello")["activation_status"] == "inactive"

    # Unauthorized activation (wrong confirm)
    with pytest.raises(PackOpsError, match="confirm"):
        engine.activate_plugin(
            plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="yes"
        )

    act = engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="activate"
    )
    assert act["ok"] is True
    assert get_plugin("demo_hello")["activation_status"] == "active"

    syn = engine.run_synthetic("demo_hello")
    assert syn["payload"]["plugin_id"] == "demo_hello"
    assert "Hello" in syn["payload"]["message"]

    engine.disable_plugin(plugin_id="demo_hello", actor="tester", confirm="disable")
    assert get_plugin("demo_hello")["activation_status"] == "disabled"

    engine.rollback_plugin(
        plugin_id="demo_hello", to="inactive", actor="tester", confirm="rollback"
    )
    assert get_plugin("demo_hello")["activation_status"] == "inactive"


def test_duplicate_version_immutable(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_plugin_from_dir(
        src, plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="install"
    )
    with pytest.raises(PackOpsError, match="immutable"):
        engine.install_plugin_from_dir(
            src, plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="install"
        )


def test_version_rollback(plugin_volume, tmp_path):
    src10 = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    src11 = _signed_demo(tmp_path, "1.1.0", plugin_volume["priv"])
    engine.install_plugin_from_dir(
        src10, plugin_id="demo_hello", version="1.0.0", actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    engine.install_plugin_from_dir(
        src11, plugin_id="demo_hello", version="1.1.0", actor="t", confirm="install"
    )
    # Active remains 1.0.0 until explicit activate
    assert get_plugin("demo_hello")["activation_status"] == "active"
    assert get_plugin("demo_hello")["version"] == "1.0.0"

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.1.0", actor="t", confirm="activate"
    )
    assert get_plugin("demo_hello")["version"] == "1.1.0"
    assert get_plugin("demo_hello")["previous_version"] == "1.0.0"

    engine.rollback_plugin(plugin_id="demo_hello", to="1.0.0", actor="t", confirm="rollback")
    assert get_plugin("demo_hello")["version"] == "1.0.0"
    assert get_plugin("demo_hello")["activation_status"] == "active"


def test_legacy_true_color_pin_untouched(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_plugin_from_dir(
        src, plugin_id="demo_hello", version="1.0.0", actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    pin = get_pin("true_color")
    assert pin["mode"] == "builtin"


def test_core_protection_script_exists():
    script = REPO / "scripts" / "tools" / "check_core_protection.py"
    core = REPO / "tools" / "core_protection.json"
    assert script.is_file()
    assert core.is_file()
    data = json.loads(core.read_text())
    ids = {m["id"] for m in data["modules"]}
    assert "authentication" in ids
    assert "existing_tool_catalog" in ids
