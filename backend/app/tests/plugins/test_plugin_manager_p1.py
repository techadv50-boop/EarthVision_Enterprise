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
    list_plugins,
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


def test_uninstall_marks_not_installed(plugin_volume, tmp_path):
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="tester", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="tester", confirm="activate"
    )
    out = engine.uninstall_plugin(
        plugin_id="demo_hello", actor="tester", confirm="uninstall"
    )
    assert out["ok"] is True
    assert out["installation_status"] == "not_installed"
    assert get_plugin("demo_hello") is None
    assert all(p.get("plugin_id") != "demo_hello" for p in list_plugins())


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


def _load_worker_executor():
    import importlib
    import sys

    worker_dir = str(REPO / "tools" / "plugins" / "worker")
    if worker_dir not in sys.path:
        sys.path.insert(0, worker_dir)
    # Fresh import of sibling modules
    for name in (
        "executor",
        "executor_core",
        "signatures",
        "auth",
        "registry_gate",
        "child_runner",
    ):
        sys.modules.pop(name, None)
    return importlib.import_module("executor")


def test_worker_executor_digest_and_lifecycle(plugin_volume, tmp_path):
    """Restricted worker executor (no FastAPI) — demo_hello 1.0.0 → 1.1.0 → rollback."""
    ex = _load_worker_executor()

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
        "EV_PLUGIN_WORKER_AUTH_TOKEN": "x" * 32,
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


def _sign_pack_dir(pack_dir: Path, priv: str, publisher_id: str = "test-pub") -> str:
    """Compute digest + write SIGNATURE.json; return digest."""
    import hashlib

    from app.tools.pack_signatures import sign_digest, write_signature_file

    sums = pack_dir / "SHA256SUMS"
    digest = "sha256:" + hashlib.sha256(sums.read_bytes()).hexdigest()
    meta = json.loads((pack_dir / "pack.json").read_text())
    meta["digest"] = digest
    (pack_dir / "pack.json").write_text(json.dumps(meta, indent=2) + "\n")
    sig = sign_digest(digest, priv)
    write_signature_file(pack_dir, digest=digest, signature=sig, publisher_id=publisher_id)
    return digest


def _evil_plugin_pack(
    tmp_path: Path,
    plugin_volume: dict,
    *,
    plugin_id: str,
    code: str,
) -> tuple[str, str]:
    """Build a minimal signed evil pack under artifacts root; return (version, digest)."""
    import hashlib

    version = "9.9.9"
    root = plugin_volume["arts"] / plugin_id / version
    if root.exists():
        shutil.rmtree(root)
    (root / "backend").mkdir(parents=True)
    (root / "ui").mkdir(parents=True)
    (root / "backend" / "plugin.py").write_text(code, encoding="utf-8")
    (root / "ui" / "tool-meta.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "frontend_slot": "results_panel",
                "permissions": ["synthetic_data", "ui.slot.results_panel", "host.sdk.read_meta"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "ui" / "synthetic.json").write_text("{}\n", encoding="utf-8")
    rels = ["backend/plugin.py", "ui/tool-meta.json", "ui/synthetic.json"]
    lines = []
    for rel in rels:
        h = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        lines.append(f"{h}  {rel}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pack_digest = "sha256:" + hashlib.sha256((root / "SHA256SUMS").read_bytes()).hexdigest()
    (root / "pack.json").write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "tool_id": plugin_id,
                "version": version,
                "digest": pack_digest,
                "host_sdk": ">=1.0.0,<2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    digest = _sign_pack_dir(root, plugin_volume["priv"])
    return version, digest


def test_p2a1_process_timeout_kills_infinite_loop(plugin_volume, tmp_path, monkeypatch):
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(plugin_volume["arts"]))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(plugin_volume["root"] / "publishers" / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    ex = _load_worker_executor()
    code = (
        "def render(_p=None):\n"
        "    while True:\n"
        "        pass\n"
    )
    version, digest = _evil_plugin_pack(
        tmp_path, plugin_volume, plugin_id="evil_loop", code=code
    )
    with pytest.raises(ex.ExecError, match="timed out"):
        ex.execute(
            plugin_id="evil_loop",
            version=version,
            digest=digest,
            operation="render",
            payload={},
            timeout_sec=1.0,
        )


def test_p2a1_process_crash_and_memory(plugin_volume, tmp_path, monkeypatch):
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(plugin_volume["arts"]))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(plugin_volume["root"] / "publishers" / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    monkeypatch.setenv("EV_PLUGIN_CHILD_AS_BYTES", str(32 * 1024 * 1024))
    ex = _load_worker_executor()

    crash_code = "def render(_p=None):\n    raise SystemExit('boom')\n"
    v, d = _evil_plugin_pack(tmp_path, plugin_volume, plugin_id="evil_crash", code=crash_code)
    with pytest.raises(ex.ExecError):
        ex.execute(plugin_id="evil_crash", version=v, digest=d, operation="render", payload={})

    mem_code = (
        "def render(_p=None):\n"
        "    x = []\n"
        "    while True:\n"
        "        x.append(bytearray(1024 * 1024))\n"
    )
    v2, d2 = _evil_plugin_pack(tmp_path / "m", plugin_volume, plugin_id="evil_mem", code=mem_code)
    with pytest.raises(ex.ExecError):
        ex.execute(
            plugin_id="evil_mem",
            version=v2,
            digest=d2,
            operation="render",
            payload={},
            timeout_sec=3.0,
        )


def test_p2a1_child_network_denied(plugin_volume, tmp_path, monkeypatch):
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(plugin_volume["arts"]))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(plugin_volume["root"] / "publishers" / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    ex = _load_worker_executor()
    code = (
        "def render(_p=None):\n"
        "    import socket\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=1)\n"
        "    return {'ok': True}\n"
    )
    v, d = _evil_plugin_pack(tmp_path, plugin_volume, plugin_id="evil_net", code=code)
    with pytest.raises(ex.ExecError, match="network disabled|Network|connection|OSError|Failed"):
        ex.execute(plugin_id="evil_net", version=v, digest=d, operation="render", payload={})


def test_p2a1_auth_and_active_pin_gate(plugin_volume, tmp_path, monkeypatch):
    """HTTP worker rejects unauthenticated / disabled / stale versions."""
    import hashlib
    import hmac as hm
    import json as json_mod
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )

    token = "t" * 32
    env = {
        **os.environ,
        "EV_ARTIFACTS_ROOT": str(plugin_volume["arts"]),
        "EV_TOOL_PACKS_ROOT": str(plugin_volume["root"]),
        "EV_PLUGIN_REGISTRY": str(plugin_volume["root"] / "plugin_registry.json"),
        "EV_PACK_PUBLISHERS": str(plugin_volume["root"] / "publishers" / "approved_publishers.json"),
        "EV_PACK_TRUST_PROFILE": "production",
        "EV_PACK_REQUIRE_SIGNATURE": "1",
        "EV_PLUGIN_WORKER_AUTH_TOKEN": token,
        "EV_PLUGIN_WORKER_ALLOW_ROOT": "1",
        # Host-unit-test only: cloud agents may have docker.sock on the host FS
        "EV_PLUGIN_WORKER_ALLOW_HOST_DOCKER_SOCK": "1",
        "EV_PLUGIN_WORKER_HOST": "127.0.0.1",
        "EV_PLUGIN_WORKER_PORT": "18091",
        # Strip Host Shell secrets — worker fail-closes if these leak in
        "DATABASE_URL": "",
        "SECRET_KEY": "",
        "MASTER_PASSWORD": "",
        "ADMIN_PASSWORD": "",
        "DOCKER_HOST": "",
        "AWS_SECRET_ACCESS_KEY": "",
        "OPENAI_API_KEY": "",
    }
    # Empty string still trips "forbidden env present" — remove keys entirely
    for k in (
        "DATABASE_URL",
        "SECRET_KEY",
        "MASTER_PASSWORD",
        "ADMIN_PASSWORD",
        "DOCKER_HOST",
        "DOCKER_SOCK",
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
    ):
        env.pop(k, None)
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tools" / "plugins" / "worker" / "server.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait for health
        deadline = time.time() + 8
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() if proc.stderr else b"") or b""
                raise AssertionError(
                    f"worker exited early rc={proc.returncode}: {err.decode('utf-8', 'replace')[:800]}"
                )
            try:
                with urllib.request.urlopen("http://127.0.0.1:18091/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            err = b""
            if proc.stderr:
                try:
                    err = proc.stderr.read()
                except Exception:  # noqa: BLE001
                    pass
            raise AssertionError(
                f"worker did not become healthy: {err.decode('utf-8', 'replace')[:800]}"
            )

        def post(body: dict, *, auth: bool = True) -> tuple[int, dict]:
            data = json_mod.dumps(body).encode()
            headers = {"Content-Type": "application/json"}
            if auth:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(
                "http://127.0.0.1:18091/v1/execute", data=data, headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json_mod.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json_mod.loads(exc.read().decode())

        rid = "a" * 32
        exp = int(time.time()) + 60
        nonce = "n" * 32
        msg = f"v2|{rid}|demo_hello|1.0.0|{d1}|{exp}|{nonce}".encode()
        mac = hm.new(token.encode(), msg, hashlib.sha256).hexdigest()
        body = {
            "schema_version": 1,
            "request_id": rid,
            "plugin_id": "demo_hello",
            "version": "1.0.0",
            "digest": d1,
            "operation": "render",
            "payload": {},
            "grant_exp": exp,
            "grant_mac": mac,
            "grant_nonce": nonce,
        }
        # Unauthorized: no bearer
        code, _ = post(body, auth=False)
        assert code == 401

        # Authorized active
        code, resp = post(body, auth=True)
        assert code == 200 and resp.get("ok") is True

        # Stale version after activate stays 1.0.0 — request fake 1.1.0 not active
        s11, d11, _ = _stage_signed(tmp_path / "stale", "1.1.0", plugin_volume["priv"])
        engine.install_from_staging(
            staging_id=s11, expected_digest=d11, actor="t", confirm="install"
        )
        rid2 = "b" * 32
        exp2 = int(time.time()) + 60
        nonce2 = "o" * 32
        msg2 = f"v2|{rid2}|demo_hello|1.1.0|{d11}|{exp2}|{nonce2}".encode()
        mac2 = hm.new(token.encode(), msg2, hashlib.sha256).hexdigest()
        body2 = {
            **body,
            "request_id": rid2,
            "version": "1.1.0",
            "digest": d11,
            "grant_exp": exp2,
            "grant_mac": mac2,
            "grant_nonce": nonce2,
        }
        code, resp = post(body2, auth=True)
        assert code == 403

        engine.disable_plugin(plugin_id="demo_hello", actor="t", confirm="disable")
        rid3 = "c" * 32
        exp3 = int(time.time()) + 60
        nonce3 = "p" * 32
        msg3 = f"v2|{rid3}|demo_hello|1.0.0|{d1}|{exp3}|{nonce3}".encode()
        mac3 = hm.new(token.encode(), msg3, hashlib.sha256).hexdigest()
        body3 = {
            **body,
            "request_id": rid3,
            "grant_exp": exp3,
            "grant_mac": mac3,
            "grant_nonce": nonce3,
        }
        code, resp = post(body3, auth=True)
        assert code == 403
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            proc.kill()


def test_p2a1_concurrent_execute_and_repeated_timeouts(plugin_volume, tmp_path, monkeypatch):
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(plugin_volume["arts"]))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(plugin_volume["root"] / "publishers" / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    ex = _load_worker_executor()
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    errors: list[BaseException] = []
    ok = {"n": 0}

    def run_ok() -> None:
        try:
            out = ex.execute(
                plugin_id="demo_hello",
                version="1.0.0",
                digest=d1,
                operation="render",
                payload={},
            )
            assert isinstance(out, dict)
            ok["n"] += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run_ok) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert ok["n"] == 6

    loop_code = "def render(_p=None):\n    while True:\n        pass\n"
    v, d = _evil_plugin_pack(tmp_path / "loop2", plugin_volume, plugin_id="evil_loop2", code=loop_code)
    for _ in range(3):
        with pytest.raises(ex.ExecError, match="timed out"):
            ex.execute(
                plugin_id="evil_loop2",
                version=v,
                digest=d,
                operation="render",
                payload={},
                timeout_sec=0.8,
            )


def test_p2a1_signature_bypass_and_bad_grant_rejected(plugin_volume, tmp_path, monkeypatch):
    """Worker cannot bypass publisher signatures; forged grants are rejected."""
    import importlib
    import json as json_mod
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    worker_dir = str(REPO / "tools" / "plugins" / "worker")
    if worker_dir not in sys.path:
        sys.path.insert(0, worker_dir)
    sys.modules.pop("signatures", None)
    sig_mod = importlib.import_module("signatures")

    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(plugin_volume["arts"]))
    monkeypatch.setenv(
        "EV_PACK_PUBLISHERS",
        str(plugin_volume["root"] / "publishers" / "approved_publishers.json"),
    )
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "0")  # attacker tries to disable
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    root = plugin_volume["arts"] / "demo_hello" / "1.0.0"
    with pytest.raises(sig_mod.SignatureError, match="refuses EV_PACK_REQUIRE_SIGNATURE=0"):
        sig_mod.verify_pack_signature(root, d1)

    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    ex = _load_worker_executor()
    # After timeout kill, worker parent must still serve new requests (restart surface)
    loop_code = "def render(_p=None):\n    while True:\n        pass\n"
    v, d = _evil_plugin_pack(tmp_path / "rst", plugin_volume, plugin_id="evil_rst", code=loop_code)
    with pytest.raises(ex.ExecError, match="timed out"):
        ex.execute(
            plugin_id="evil_rst",
            version=v,
            digest=d,
            operation="render",
            payload={},
            timeout_sec=0.6,
        )
    ok = ex.execute(
        plugin_id="demo_hello",
        version="1.0.0",
        digest=d1,
        operation="render",
        payload={},
    )
    assert isinstance(ok, dict)

    # Forged grant MAC rejected by live worker
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    token = "u" * 32
    env = {
        **os.environ,
        "EV_ARTIFACTS_ROOT": str(plugin_volume["arts"]),
        "EV_TOOL_PACKS_ROOT": str(plugin_volume["root"]),
        "EV_PLUGIN_REGISTRY": str(plugin_volume["root"] / "plugin_registry.json"),
        "EV_PACK_PUBLISHERS": str(plugin_volume["root"] / "publishers" / "approved_publishers.json"),
        "EV_PACK_TRUST_PROFILE": "production",
        "EV_PACK_REQUIRE_SIGNATURE": "1",
        "EV_PLUGIN_WORKER_AUTH_TOKEN": token,
        "EV_PLUGIN_WORKER_ALLOW_ROOT": "1",
        "EV_PLUGIN_WORKER_ALLOW_HOST_DOCKER_SOCK": "1",
        "EV_PLUGIN_WORKER_HOST": "127.0.0.1",
        "EV_PLUGIN_WORKER_PORT": "18093",
    }
    for k in (
        "DATABASE_URL",
        "SECRET_KEY",
        "MASTER_PASSWORD",
        "ADMIN_PASSWORD",
        "DOCKER_HOST",
        "DOCKER_SOCK",
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
    ):
        env.pop(k, None)
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tools" / "plugins" / "worker" / "server.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 8
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() if proc.stderr else b"") or b""
                raise AssertionError(err.decode("utf-8", "replace")[:500])
            try:
                with urllib.request.urlopen("http://127.0.0.1:18093/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise AssertionError("worker unhealthy")
        rid = "d" * 32
        exp = int(time.time()) + 60
        body = {
            "schema_version": 1,
            "request_id": rid,
            "plugin_id": "demo_hello",
            "version": "1.0.0",
            "digest": d1,
            "operation": "render",
            "payload": {},
            "grant_exp": exp,
            "grant_mac": "0" * 64,  # forged
            "grant_nonce": "q" * 32,
        }
        data = json_mod.dumps(body).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:18093/v1/execute",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=10)
        assert ei.value.code == 401
        # plugin id/version/digest alone are not auth — even with bearer, grant required
        body2 = {
            k: v
            for k, v in body.items()
            if k not in {"grant_exp", "grant_mac", "grant_nonce"}
        }
        data2 = json_mod.dumps(body2).encode()
        req2 = urllib.request.Request(
            "http://127.0.0.1:18093/v1/execute",
            data=data2,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei2:
            urllib.request.urlopen(req2, timeout=10)
        assert ei2.value.code == 401
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            proc.kill()


def test_p2a1_branch_protection_evidence_unknown_or_pass():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "tools" / "check_branch_protection_evidence.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["overall"] in {"PASS", "UNKNOWN"}
    assert data["local_codeowners"]["codeowners_present"] is True


# ---------------------------------------------------------------------------
# Stage P2B — sandboxed frontend plugin loading
# ---------------------------------------------------------------------------


def test_p2b_frontend_manifest_and_assets_bound_to_active_pin(plugin_volume, tmp_path):
    from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset

    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    with pytest.raises(PackOpsError, match="not active"):
        active_frontend_manifest("demo_hello")

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    man = active_frontend_manifest("demo_hello")
    assert man["version"] == "1.0.0"
    assert man["digest"] == d1
    assert man["ui_strategy"] == "sandboxed_iframe"
    assert man["entry_html"] == "ui/panel.html"
    assert "ui/plugin.js" in man["ui_files"]

    html, ctype = read_active_ui_asset("demo_hello", "panel.html")
    assert b"Demo Hello" in html
    assert "text/html" in ctype

    # Path traversal / non-listed asset
    with pytest.raises(PackOpsError):
        read_active_ui_asset("demo_hello", "../pack.json")
    with pytest.raises(PackOpsError):
        read_active_ui_asset("demo_hello", "ui/../../pack.json")


def test_p2b_frontend_version_update_and_rollback_changes_ui(plugin_volume, tmp_path):
    from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset

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
    html10, _ = read_active_ui_asset("demo_hello", "ui/panel.html")
    assert b"#0369a1" in html10

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.1.0", actor="t", confirm="activate"
    )
    man = active_frontend_manifest("demo_hello")
    assert man["version"] == "1.1.0" and man["digest"] == d11
    html11, _ = read_active_ui_asset("demo_hello", "ui/panel.html")
    assert b"#047857" in html11
    js11, _ = read_active_ui_asset("demo_hello", "plugin.js")
    assert b"FE 1.1.0" in js11

    engine.rollback_plugin(
        plugin_id="demo_hello", to="1.0.0", actor="t", confirm="rollback"
    )
    man2 = active_frontend_manifest("demo_hello")
    assert man2["version"] == "1.0.0" and man2["digest"] == d10
    html_rb, _ = read_active_ui_asset("demo_hello", "panel.html")
    assert b"#0369a1" in html_rb


def test_p2b_host_sdk_message_validation_adversarial():
    from app.plugins.host_sdk_contract import (
        HostSdkError,
        assert_method_allowed,
        validate_plugin_message,
    )

    base = {
        "v": 1,
        "type": "request",
        "id": "r1",
        "plugin_id": "demo_hello",
        "version": "1.0.0",
        "digest": "sha256:" + ("ab" * 32),
        "method": "host.meta",
        "params": {},
    }
    assert validate_plugin_message(base)["method"] == "host.meta"

    with pytest.raises(HostSdkError, match="protocol"):
        validate_plugin_message({**base, "v": 99})
    with pytest.raises(HostSdkError, match="type"):
        validate_plugin_message({**base, "type": "exec"})
    with pytest.raises(HostSdkError, match="forbidden"):
        assert_method_allowed("host.getAuthToken", ["host.sdk.read_meta"])
    with pytest.raises(HostSdkError, match="forbidden"):
        assert_method_allowed("host.leaflet", ["host.sdk.read_meta"])
    with pytest.raises(HostSdkError, match="unknown"):
        assert_method_allowed("host.notARealMethod", ["host.sdk.read_meta"])
    with pytest.raises(HostSdkError, match="permission"):
        assert_method_allowed("host.getSynthetic", ["host.sdk.read_meta"])
    with pytest.raises(HostSdkError, match="secrets"):
        validate_plugin_message({**base, "params": {"token": "steal-me"}})
    with pytest.raises(HostSdkError, match="digest"):
        validate_plugin_message({**base, "digest": "md5:dead"})


def test_p2b_host_sdk_bridge_rejects_stale_and_disabled(plugin_volume, tmp_path):
    from app.plugins.host_sdk_contract import (
        assert_method_allowed,
        validate_plugin_message,
    )

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

    # Simulate bridge pin checks (same as router)
    def bridge(version: str, digest: str, method: str = "host.meta"):
        msg = validate_plugin_message(
            {
                "v": 1,
                "type": "request",
                "id": "x1",
                "plugin_id": "demo_hello",
                "version": version,
                "digest": digest,
                "method": method,
                "params": {},
            }
        )
        rec = get_plugin("demo_hello")
        assert rec
        if rec.get("activation_status") != "active":
            raise PackOpsError("plugin not active")
        if str(rec.get("version")) != msg["version"]:
            raise PackOpsError("stale or rolled-back version")
        if str(rec.get("digest") or "") != msg["digest"]:
            raise PackOpsError("digest does not match active pin")
        assert_method_allowed(msg["method"], list(rec.get("permissions") or []))
        return True

    assert bridge("1.0.0", d10) is True
    with pytest.raises(PackOpsError, match="stale|rolled-back"):
        bridge("1.1.0", d11)
    with pytest.raises(PackOpsError, match="digest"):
        bridge("1.0.0", d11)

    engine.disable_plugin(plugin_id="demo_hello", actor="t", confirm="disable")
    with pytest.raises(PackOpsError, match="not active"):
        bridge("1.0.0", d10)


def test_p2b_unsupported_sdk_and_invalid_signature_still_blocked(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    meta = json.loads((src / "pack.json").read_text())
    meta["host_sdk"] = ">=9.0.0,<10"
    (src / "pack.json").write_text(json.dumps(meta, indent=2) + "\n")
    with pytest.raises(PackOpsError, match="incompatible"):
        engine.validate_plugin_package(src)

    src2 = _signed_demo(tmp_path / "bad", "1.0.0", plugin_volume["priv"])
    sig = json.loads((src2 / "SIGNATURE.json").read_text())
    sig["signature"] = "AAAA"
    (src2 / "SIGNATURE.json").write_text(json.dumps(sig))
    with pytest.raises(PackOpsError):
        engine.validate_plugin_package(src2)


def test_p2b_disabled_plugin_cannot_serve_ui(plugin_volume, tmp_path):
    from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset

    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    engine.disable_plugin(plugin_id="demo_hello", actor="t", confirm="disable")
    with pytest.raises(PackOpsError, match="not active"):
        active_frontend_manifest("demo_hello")
    with pytest.raises(PackOpsError, match="not active"):
        read_active_ui_asset("demo_hello", "panel.html")


def test_p2b_audit_redacts_secrets_and_health_has_no_tokens(plugin_volume, tmp_path):
    engine.audit_frontend_event(
        action="host_sdk",
        ok=False,
        plugin_id="demo_hello",
        error="denied",
        extra={"authorization": "Bearer SECRET", "method": "host.meta"},
    )
    events = engine.read_audit_history(limit=20)
    assert events
    # authorization key should be redacted or omitted from extra
    for ev in events:
        if ev.get("action") == "host_sdk":
            assert ev.get("authorization") in (None, "[redacted]")
            assert "SECRET" not in json.dumps(ev)

    health = engine.plugin_system_health()
    blob = json.dumps(health)
    assert "password" not in blob.lower() or health.get("ok")
    assert "EV_PLUGIN_WORKER_AUTH_TOKEN" not in blob
    assert health["loading_model"] == "sandboxed_iframe_srcdoc"
    assert health["host_sdk_version"] == "1.4.0"


def test_p2b_sandboxed_iframe_requires_panel_and_plugin_js(plugin_volume, tmp_path):
    src = _signed_demo(tmp_path, "1.0.0", plugin_volume["priv"])
    (src / "ui" / "plugin.js").unlink()
    # Recompute sums without plugin.js so verify_pack_at path differs —
    # validate checks file presence before full verify for strategy.
    with pytest.raises(PackOpsError, match="plugin.js"):
        engine.validate_plugin_package(src)


def test_p2b_true_color_pin_preserved(plugin_volume, tmp_path):
    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    assert get_pin("true_color")["mode"] == "builtin"


def test_rc_replay_resistant_grant(plugin_volume, tmp_path, monkeypatch):
    import hashlib
    import hmac as hm
    import json as json_mod
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request

    s1, d1, _ = _stage_signed(tmp_path, "1.0.0", plugin_volume["priv"])
    engine.install_from_staging(
        staging_id=s1, expected_digest=d1, actor="t", confirm="install"
    )
    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="t", confirm="activate"
    )
    token = "r" * 32
    env = {
        **os.environ,
        "EV_ARTIFACTS_ROOT": str(plugin_volume["arts"]),
        "EV_TOOL_PACKS_ROOT": str(plugin_volume["root"]),
        "EV_PLUGIN_REGISTRY": str(plugin_volume["root"] / "plugin_registry.json"),
        "EV_PACK_PUBLISHERS": str(
            plugin_volume["root"] / "publishers" / "approved_publishers.json"
        ),
        "EV_PACK_TRUST_PROFILE": "production",
        "EV_PACK_REQUIRE_SIGNATURE": "1",
        "EV_PLUGIN_WORKER_AUTH_TOKEN": token,
        "EV_PLUGIN_WORKER_ALLOW_ROOT": "1",
        "EV_PLUGIN_WORKER_ALLOW_HOST_DOCKER_SOCK": "1",
        "EV_PLUGIN_WORKER_HOST": "127.0.0.1",
        "EV_PLUGIN_WORKER_PORT": "18094",
        "EV_PLUGIN_WORKER_TLS": "0",
    }
    for k in (
        "DATABASE_URL",
        "SECRET_KEY",
        "MASTER_PASSWORD",
        "ADMIN_PASSWORD",
        "DOCKER_HOST",
        "DOCKER_SOCK",
        "AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
    ):
        env.pop(k, None)
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tools" / "plugins" / "worker" / "server.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 8
        while time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError("worker exited")
            try:
                with urllib.request.urlopen("http://127.0.0.1:18094/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise AssertionError("worker unhealthy")
        rid = "e" * 32
        exp = int(time.time()) + 60
        nonce = "s" * 32
        msg = f"v2|{rid}|demo_hello|1.0.0|{d1}|{exp}|{nonce}".encode()
        mac = hm.new(token.encode(), msg, hashlib.sha256).hexdigest()
        body = {
            "schema_version": 1,
            "request_id": rid,
            "plugin_id": "demo_hello",
            "version": "1.0.0",
            "digest": d1,
            "operation": "ping",
            "payload": {},
            "grant_exp": exp,
            "grant_mac": mac,
            "grant_nonce": nonce,
        }
        data = json_mod.dumps(body).encode()

        def post_once():
            req = urllib.request.Request(
                "http://127.0.0.1:18094/v1/execute",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json_mod.loads(resp.read().decode())

        code, resp = post_once()
        assert code == 200 and resp.get("ok") is True
        with pytest.raises(urllib.error.HTTPError) as ei:
            post_once()
        assert ei.value.code == 401
        assert b"replay" in ei.value.read().lower()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            proc.kill()


def test_rc_demo_gis_analysis_lifecycle(plugin_volume, tmp_path):
    from app.plugins.frontend_assets import active_frontend_manifest
    from app.plugins.host_sdk_contract import (
        assert_method_allowed,
        store_analysis_result,
        load_analysis_result,
    )

    gis_art = REPO / "tools" / "plugins" / "demo_gis_analysis" / "artifacts" / "1.0.0"
    if not (gis_art / "pack.json").is_file():
        pytest.skip("demo_gis_analysis artifact missing — build first")

    dest = tmp_path / "gis"
    shutil.copytree(gis_art, dest)
    meta = verify_pack_at(dest, "demo_gis_analysis", "1.0.0")
    sig = sign_digest(meta["digest"], plugin_volume["priv"])
    write_signature_file(
        dest, digest=meta["digest"], signature=sig, publisher_id="test-pub"
    )
    zpath = tmp_path / "gis.zip"
    _zip_pack(dest, zpath)
    with zpath.open("rb") as fh:
        staging_id = stream_upload_to_staging(fh)
    validated = engine.validate_staging(staging_id)
    assert validated["ok"] is True
    assert "host.sdk.read_aoi" in validated["permissions"]
    engine.install_from_staging(
        staging_id=staging_id,
        expected_digest=validated["digest"],
        actor="t",
        confirm="install",
    )
    assert get_plugin("demo_gis_analysis")["activation_status"] == "inactive"
    engine.activate_plugin(
        plugin_id="demo_gis_analysis",
        version="1.0.0",
        actor="t",
        confirm="activate",
    )
    man = active_frontend_manifest("demo_gis_analysis")
    assert man["frontend_slot"] == "right_analysis_panel"
    assert man["ui_strategy"] == "sandboxed_iframe"
    syn = engine.run_synthetic("demo_gis_analysis")
    assert syn["payload"]["plugin_id"] == "demo_gis_analysis"
    assert_method_allowed(
        "host.setAnalysisResult",
        list(get_plugin("demo_gis_analysis")["permissions"]),
    )
    store_analysis_result(
        plugin_id="demo_gis_analysis",
        version="1.0.0",
        digest=validated["digest"],
        result={"title": "t", "summary": "ok", "metrics": []},
    )
    assert load_analysis_result("demo_gis_analysis")["result"]["summary"] == "ok"
    engine.disable_plugin(
        plugin_id="demo_gis_analysis", actor="t", confirm="disable"
    )
    assert get_plugin("demo_gis_analysis")["activation_status"] == "disabled"
    assert get_pin("true_color")["mode"] == "builtin"


def test_optical_true_color_plugin_lifecycle(plugin_volume, tmp_path):
    from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset
    from app.plugins.host_sdk_contract import assert_method_allowed

    art = REPO / "tools" / "plugins" / "optical_true_color" / "artifacts" / "1.0.0"
    if not (art / "pack.json").is_file():
        pytest.skip("optical_true_color artifact missing — build first")

    dest = tmp_path / "otc"
    shutil.copytree(art, dest)
    meta = verify_pack_at(dest, "optical_true_color", "1.0.0")
    sig = sign_digest(meta["digest"], plugin_volume["priv"])
    write_signature_file(
        dest, digest=meta["digest"], signature=sig, publisher_id="test-pub"
    )
    zpath = tmp_path / "otc.zip"
    _zip_pack(dest, zpath)
    with zpath.open("rb") as fh:
        staging_id = stream_upload_to_staging(fh)
    validated = engine.validate_staging(staging_id)
    assert validated["ok"] is True
    for need in (
        "host.sdk.read_scene",
        "host.sdk.render_true_color",
        "host.sdk.export_geotiff",
        "host.sdk.export_map_jpeg",
    ):
        assert need in validated["permissions"]
    engine.install_from_staging(
        staging_id=staging_id,
        expected_digest=validated["digest"],
        actor="t",
        confirm="install",
    )
    engine.activate_plugin(
        plugin_id="optical_true_color",
        version="1.0.0",
        actor="t",
        confirm="activate",
    )
    man = active_frontend_manifest("optical_true_color")
    assert man["frontend_slot"] == "right_analysis_panel"
    assert man["ui_strategy"] == "sandboxed_iframe"
    perms = list(get_plugin("optical_true_color")["permissions"])
    assert_method_allowed("host.getSceneContext", perms)
    assert_method_allowed("host.renderTrueColor", perms)
    assert_method_allowed("host.exportGeotiff", perms)
    assert_method_allowed("host.exportMapJpeg", perms)
    html, _ = read_active_ui_asset("optical_true_color", "panel.html")
    assert b"True Color" in html
    js, _ = read_active_ui_asset("optical_true_color", "plugin.js")
    assert b"host.renderTrueColor" in js
    assert b"host.exportMapJpeg" in js
    # Legacy frozen id remains reserved
    assert get_pin("true_color")["mode"] == "builtin"
    engine.disable_plugin(
        plugin_id="optical_true_color", actor="t", confirm="disable"
    )


def test_rc_no_default_worker_token_in_production_profile(monkeypatch):
    from app.plugins import worker_client

    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv(
        "EV_PLUGIN_WORKER_AUTH_TOKEN", "preview-plugin-worker-auth-token-32b!!"
    )
    with pytest.raises(PackOpsError, match="forbidden|default|preview"):
        worker_client._auth_token()
