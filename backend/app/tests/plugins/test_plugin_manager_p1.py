"""Stage P1 / P1.1 — Plugin Manager foundation + security hardenings."""

from __future__ import annotations

import io
import json
import os
import shutil
import threading
import zipfile
from pathlib import Path

import pytest

from app.plugins import engine
from app.plugins.permissions import FORBIDDEN_PERMISSIONS, validate_permissions
from app.plugins.registry import (
    PluginRegistryError,
    get_plugin,
    load_registry,
    mutate_registry,
    validate_plugin_id,
)
from app.plugins.slots import SUPPORTED_SLOTS, validate_slot
from app.plugins.staging import (
    MAX_ARCHIVE_ENTRIES,
    expire_stale_staging,
    stream_upload_to_staging,
)
from app.tools.pack_loader import verify_pack, verify_pack_at
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
    meta = verify_pack_at(dest, "demo_hello", version)
    sig = sign_digest(meta["digest"], priv)
    write_signature_file(dest, digest=meta["digest"], signature=sig, publisher_id="test-pub")
    return dest


def _zip_pack(pack_dir: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in pack_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(pack_dir)))
    return zip_path


def _stage_signed(tmp_path: Path, version: str, priv: str) -> tuple[str, str, Path]:
    pack = _signed_demo(tmp_path, version, priv)
    zpath = tmp_path / f"{version}.zip"
    _zip_pack(pack, zpath)
    with zpath.open("rb") as fh:
        staging_id = stream_upload_to_staging(fh)
    validated = engine.validate_staging(staging_id)
    return staging_id, validated["digest"], pack


def test_supported_slots():
    assert "left_toolbar" in SUPPORTED_SLOTS
    assert "right_analysis_panel" in SUPPORTED_SLOTS
    with pytest.raises(ValueError, match="invalid UI slot"):
        validate_slot("evil_slot")


def test_permission_validation():
    assert validate_permissions(["synthetic_data"]) == ["synthetic_data"]
    for bad in FORBIDDEN_PERMISSIONS:
        with pytest.raises(ValueError):
            validate_permissions([bad])


def test_plugin_id_rejects_legacy():
    with pytest.raises(PluginRegistryError, match="frozen legacy"):
        validate_plugin_id("true_color")
    with pytest.raises(PluginRegistryError, match="frozen legacy"):
        validate_plugin_id("ship_detection")


def test_invalid_signature_rejected(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
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
    with pytest.raises(PackOpsError, match="incompatible"):
        engine.validate_plugin_package(src)


def test_invalid_slot_in_meta(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    ui = json.loads((src / "ui" / "tool-meta.json").read_text())
    ui["frontend_slot"] = "not_a_slot"
    (src / "ui" / "tool-meta.json").write_text(json.dumps(ui, indent=2) + "\n")
    with pytest.raises(PackOpsError, match="invalid UI slot"):
        engine.validate_plugin_package(src)


def test_install_activate_disable_rollback_via_staging(plugin_volume, tmp_path):
    staging_id, digest, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    installed = engine.install_from_staging(
        staging_id=staging_id,
        expected_digest=digest,
        actor="tester",
        confirm="install",
    )
    assert installed["activation_status"] == "inactive"
    assert get_plugin("demo_hello")["activation_status"] == "inactive"

    with pytest.raises(PackOpsError, match="confirm"):
        engine.activate_plugin(
            plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="yes"
        )

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="activate"
    )
    syn = engine.run_synthetic("demo_hello")
    assert syn["execution_model"] == "static_synthetic_only"
    assert syn["payload"]["plugin_id"] == "demo_hello"
    assert "Hello" in syn["payload"]["message"]

    engine.disable_plugin(plugin_id="demo_hello", actor="tester", confirm="disable")
    engine.rollback_plugin(
        plugin_id="demo_hello", to="inactive", actor="tester", confirm="rollback"
    )
    assert get_plugin("demo_hello")["activation_status"] == "inactive"


def test_digest_mismatch_refuses_install(plugin_volume, tmp_path):
    staging_id, digest, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    with pytest.raises(PackOpsError, match="digest mismatch"):
        engine.install_from_staging(
            staging_id=staging_id,
            expected_digest="sha256:" + ("ab" * 32),
            actor="tester",
            confirm="install",
        )
    assert digest.startswith("sha256:")


def test_duplicate_version_immutable(plugin_volume, tmp_path):
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="tester", confirm="install"
    )
    s2, d2, _ = _stage_signed(tmp_path / "b", "1.0.0", plugin_volume["priv"])
    with pytest.raises(PackOpsError, match="immutable"):
        engine.install_from_staging(
            staging_id=s2, expected_digest=d2, actor="tester", confirm="install"
        )


def test_version_rollback(plugin_volume, tmp_path):
    s10, d10, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s10, expected_digest=d10, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    s11, d11, _ = _stage_signed(tmp_path / "v11", "1.1.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s11, expected_digest=d11, actor="t", confirm="install"
    )
    assert get_plugin("demo_hello")["version"] == "1.0.0"
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.1.0", actor="t", confirm="activate"
    )
    engine.rollback_plugin(plugin_id="demo_hello", to="1.0.0", actor="t", confirm="rollback")
    assert get_plugin("demo_hello")["version"] == "1.0.0"


def test_legacy_true_color_pin_untouched(plugin_volume, tmp_path):
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    assert get_pin("true_color")["mode"] == "builtin"


def test_no_env_mutation_during_validate(plugin_volume, tmp_path, monkeypatch):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    before = os.environ.get("EV_ARTIFACTS_ROOT")
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", before or str(plugin_volume["arts"]))
    marker = {"mutated": False}
    real_setitem = os.environ.__setitem__

    def watch(key, val):  # noqa: ANN001
        if key == "EV_ARTIFACTS_ROOT":
            marker["mutated"] = True
        return real_setitem(key, val)

    monkeypatch.setattr(os.environ, "__setitem__", watch)
    engine.validate_plugin_package(src)
    assert marker["mutated"] is False
    assert os.environ.get("EV_ARTIFACTS_ROOT") == before or str(plugin_volume["arts"])


def test_zip_traversal_rejected(plugin_volume, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape/pack.json", "{}")
    with evil.open("rb") as fh, pytest.raises(PackOpsError, match="unsafe"):
        stream_upload_to_staging(fh)


def test_zip_entry_limit(plugin_volume, tmp_path):
    zpath = tmp_path / "many.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for i in range(MAX_ARCHIVE_ENTRIES + 5):
            zf.writestr(f"f{i}.txt", "x")
    with zpath.open("rb") as fh, pytest.raises(PackOpsError, match="entry count"):
        stream_upload_to_staging(fh)


def test_concurrent_validate_and_registry(plugin_volume, tmp_path):
    errors: list[BaseException] = []
    install_ok = {"n": 0}
    lock = threading.Lock()

    def worker_install(idx: int) -> None:
        try:
            s, d, _ = _stage_signed(tmp_path / f"w{idx}", "1.0.0", plugin_volume["priv"])
            try:
                engine.install_from_staging(
                    staging_id=s, expected_digest=d, actor=f"w{idx}", confirm="install"
                )
                with lock:
                    install_ok["n"] += 1
            except PackOpsError as exc:
                if "immutable" not in str(exc):
                    raise
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def worker_registry(idx: int) -> None:
        try:
            pid = f"conc_{idx}"

            def _mut(data):
                from app.plugins.registry import make_record

                data.setdefault("plugins", {})[pid] = make_record(
                    plugin_id=pid,
                    name=pid,
                    description="concurrency",
                    version="0.0.1",
                    compatible_host_api=">=1.0.0,<2",
                    backend_entrypoint="backend/plugin.py",
                    frontend_slot="results_panel",
                    permissions=["host.sdk.read_meta"],
                )
                return pid

            mutate_registry(_mut)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker_registry, args=(i,)) for i in range(8)]
    threads += [threading.Thread(target=worker_install, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert install_ok["n"] == 1
    for i in range(8):
        assert get_plugin(f"conc_{i}") is not None
    assert get_plugin("demo_hello")["installation_status"] == "installed"


def test_run_synthetic_does_not_import_plugin_py(plugin_volume, tmp_path, monkeypatch):
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )

    def boom(*_a, **_k):
        raise AssertionError("load_pack_module must not be called in P1.1")

    monkeypatch.setattr("app.tools.pack_loader.load_pack_module", boom)
    syn = engine.run_synthetic("demo_hello")
    assert syn["execution_model"] == "static_synthetic_only"
    assert isinstance(syn["payload"], dict)


def test_core_protection_script_exists():
    script = REPO / "scripts" / "tools" / "check_core_protection.py"
    core = REPO / "tools" / "core_protection.json"
    assert script.is_file()
    data = json.loads(core.read_text())
    assert data.get("schema_version") == 2
    assert "rejects_standalone_env" in (data.get("approval") or {})


def test_registry_flock_fail_closed(plugin_volume, monkeypatch):
    import fcntl

    from app.plugins import registry as reg

    def boom_flock(*_a, **_k):
        raise OSError("flock denied")

    monkeypatch.setattr(fcntl, "flock", boom_flock)
    with pytest.raises(reg.PluginRegistryError, match="locking unavailable"):
        with reg.registry_lock():
            pass


def test_concurrent_activate_and_rollback(plugin_volume, tmp_path):
    s10, d10, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    s11, d11, _ = _stage_signed(tmp_path / "b", "1.1.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s10, expected_digest=d10, actor="t", confirm="install"
    )
    engine.install_from_staging(
        staging_id=s11, expected_digest=d11, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    errors: list[BaseException] = []

    def activate_11() -> None:
        try:
            engine.activate_plugin(
                plugin_id="demo_hello", version="1.1.0", actor="a11", confirm="activate"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def rollback_10() -> None:
        try:
            engine.rollback_plugin(
                plugin_id="demo_hello", to="1.0.0", actor="r10", confirm="rollback"
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=activate_11),
        threading.Thread(target=rollback_10),
        threading.Thread(target=activate_11),
        threading.Thread(target=rollback_10),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    rec = get_plugin("demo_hello")
    assert rec["activation_status"] == "active"
    assert rec["version"] in {"1.0.0", "1.1.0"}
    assert get_pin("true_color")["mode"] == "builtin"


def test_worker_required_fail_closed(plugin_volume, tmp_path, monkeypatch):
    from app.plugins import worker_client

    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    monkeypatch.setenv("EV_PLUGIN_WORKER_REQUIRED", "1")
    monkeypatch.delenv("EV_PLUGIN_WORKER_URL", raising=False)
    with pytest.raises(PackOpsError, match="isolation cannot be established|WORKER_URL"):
        worker_client.check_isolation(require=True)
    with pytest.raises(PackOpsError, match="worker"):
        engine.run_synthetic("demo_hello")


def test_worker_executor_digest_and_lifecycle(plugin_volume, tmp_path):
    """Restricted worker executor (no FastAPI) — demo_hello 1.0.0 → 1.1.0 → rollback."""
    import importlib.util

    worker_dir = REPO / "tools" / "plugins" / "worker"
    spec = importlib.util.spec_from_file_location(
        "ev_p2a_executor", worker_dir / "executor.py"
    )
    assert spec and spec.loader
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)

    s10, d10, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    s11, d11, _ = _stage_signed(tmp_path / "c", "1.1.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s10, expected_digest=d10, actor="t", confirm="install"
    )
    engine.install_from_staging(
        staging_id=s11, expected_digest=d11, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )

    out10 = ex.execute(
        plugin_id="demo_hello",
        version="1.0.0",
        digest=d10,
        operation="render",
        payload={},
    )
    assert out10["plugin_id"] == "demo_hello"
    assert "1.0.0" in str(out10.get("version")) or "Hello" in out10.get("message", "")

    with pytest.raises(ex.ExecError, match="digest"):
        ex.execute(
            plugin_id="demo_hello",
            version="1.0.0",
            digest="sha256:" + ("00" * 32),
            operation="render",
            payload={},
        )

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.1.0", actor="t", confirm="activate"
    )
    out11 = ex.execute(
        plugin_id="demo_hello",
        version="1.1.0",
        digest=d11,
        operation="render",
        payload={},
    )
    assert "1.1.0" in out11.get("message", "") or out11.get("version") == "1.1.0"

    engine.rollback_plugin(
        plugin_id="demo_hello", to="1.0.0", actor="t", confirm="rollback"
    )
    assert get_plugin("demo_hello")["version"] == "1.0.0"
    engine.disable_plugin(plugin_id="demo_hello", actor="t", confirm="disable")
    assert get_plugin("demo_hello")["activation_status"] == "disabled"
    assert get_pin("true_color")["mode"] == "builtin"


def test_worker_server_isolation_refuses_secrets(tmp_path, monkeypatch):
    """Worker server must refuse start when Host Shell secrets are present."""
    import subprocess
    import sys

    env = {
        **os.environ,
        "EV_ARTIFACTS_ROOT": str(tmp_path),
        "DATABASE_URL": "postgresql://should-not-exist",
        "SECRET_KEY": "",
        # Allow root in CI sandboxes; still must fail on DATABASE_URL
        "EV_PLUGIN_WORKER_ALLOW_ROOT": "1",
    }
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "plugins" / "worker" / "server.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 2
    assert "ISOLATION FAILED" in (proc.stderr or "") or "DATABASE_URL" in (proc.stderr or "")
