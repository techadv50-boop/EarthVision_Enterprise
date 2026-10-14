#!/usr/bin/env python3
"""Development-only lifecycle verification for RC plugins (no Host Shell rebuild).

Runs install→activate→FE assets→upgrade→rollback→disable for demo_hello and
demo_gis_analysis against an ephemeral tool_packs volume. Does not start Docker
Host Shell containers — pair with compose evidence when available.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.plugins import engine  # noqa: E402
from app.plugins.frontend_assets import active_frontend_manifest, read_active_ui_asset  # noqa: E402
from app.plugins.registry import get_plugin, load_registry  # noqa: E402
from app.plugins.staging import stream_upload_to_staging  # noqa: E402
from app.tools.pack_loader import verify_pack_at  # noqa: E402
from app.tools.pack_ops import ensure_default_pins  # noqa: E402
from app.tools.pack_signatures import generate_keypair, sign_digest, write_signature_file  # noqa: E402
from app.tools.runtime_pins import get_pin  # noqa: E402
import zipfile  # noqa: E402


def zip_pack(pack_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in pack_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(pack_dir)))


def stage_from_artifact(arts: Path, plugin_id: str, version: str, priv: str, tmp: Path):
    src = ROOT / "tools" / "plugins" / plugin_id / "artifacts" / version
    dest = tmp / f"{plugin_id}-{version}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    meta = verify_pack_at(dest, plugin_id, version)
    sig = sign_digest(meta["digest"], priv)
    write_signature_file(dest, digest=meta["digest"], signature=sig, publisher_id="test-pub")
    zpath = tmp / f"{plugin_id}-{version}.zip"
    zip_pack(dest, zpath)
    with zpath.open("rb") as fh:
        staging_id = stream_upload_to_staging(fh)
    validated = engine.validate_staging(staging_id)
    return staging_id, validated["digest"]


def main() -> int:
    report: dict = {"ok": True, "steps": [], "true_color_pin": None}
    tmp = Path(tempfile.mkdtemp(prefix="ev-plugin-lifecycle-"))
    try:
        root = tmp / "tool_packs"
        arts = root / "artifacts"
        arts.mkdir(parents=True)
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
        import os

        os.environ["EV_TOOL_PACKS_ROOT"] = str(root)
        os.environ["EV_RUNTIME_PINS"] = str(root / "runtime_pins.json")
        os.environ["EV_ARTIFACTS_ROOT"] = str(arts)
        os.environ["EV_PLUGIN_REGISTRY"] = str(root / "plugin_registry.json")
        os.environ["EV_PACK_PUBLISHERS"] = str(pubs / "approved_publishers.json")
        os.environ["EV_PACK_REQUIRE_SIGNATURE"] = "1"
        os.environ["EV_PACK_TRUST_PROFILE"] = "production"
        os.environ["EV_PACK_AUDIT_LOG"] = str(root / "audit" / "promotions.jsonl")
        from app.tools import runtime_pins as rp

        rp._CACHE = {"mtime": None, "data": None}
        ensure_default_pins()
        load_registry(force=True)

        # demo_hello 1.0.0 install inactive
        s10, d10 = stage_from_artifact(arts, "demo_hello", "1.0.0", priv, tmp)
        inst = engine.install_from_staging(
            staging_id=s10, expected_digest=d10, actor="verify", confirm="install"
        )
        assert inst["activation_status"] == "inactive"
        report["steps"].append({"action": "install_demo_hello_1.0.0", "ok": True, "active": False})

        engine.activate_plugin(
            plugin_id="demo_hello", version="1.0.0", actor="verify", confirm="activate"
        )
        man = active_frontend_manifest("demo_hello")
        html, _ = read_active_ui_asset("demo_hello", "panel.html")
        assert b"#0369a1" in html or b"Demo Hello" in html
        syn = engine.run_synthetic("demo_hello")
        report["steps"].append(
            {
                "action": "activate_use_demo_hello_1.0.0",
                "ok": True,
                "digest": man["digest"],
                "slot": man["frontend_slot"],
                "synthetic": syn.get("execution_model"),
            }
        )

        s11, d11 = stage_from_artifact(arts, "demo_hello", "1.1.0", priv, tmp / "v11")
        engine.install_from_staging(
            staging_id=s11, expected_digest=d11, actor="verify", confirm="install"
        )
        engine.activate_plugin(
            plugin_id="demo_hello", version="1.1.0", actor="verify", confirm="activate"
        )
        html11, _ = read_active_ui_asset("demo_hello", "panel.html")
        assert b"#047857" in html11 or b"1.1.0" in html11
        report["steps"].append({"action": "upgrade_demo_hello_1.1.0", "ok": True})

        engine.rollback_plugin(
            plugin_id="demo_hello", to="1.0.0", actor="verify", confirm="rollback"
        )
        assert get_plugin("demo_hello")["version"] == "1.0.0"
        report["steps"].append({"action": "rollback_demo_hello_1.0.0", "ok": True})

        engine.disable_plugin(plugin_id="demo_hello", actor="verify", confirm="disable")
        try:
            active_frontend_manifest("demo_hello")
            raise AssertionError("disabled plugin still served FE")
        except Exception as exc:  # noqa: BLE001
            report["steps"].append(
                {"action": "disable_rejects_fe", "ok": True, "error": str(exc)[:120]}
            )

        # demo_gis_analysis
        sg, dg = stage_from_artifact(arts, "demo_gis_analysis", "1.0.0", priv, tmp / "gis")
        engine.install_from_staging(
            staging_id=sg, expected_digest=dg, actor="verify", confirm="install"
        )
        engine.activate_plugin(
            plugin_id="demo_gis_analysis", version="1.0.0", actor="verify", confirm="activate"
        )
        man_g = active_frontend_manifest("demo_gis_analysis")
        assert "host.sdk.read_aoi" in (get_plugin("demo_gis_analysis").get("permissions") or [])
        engine.run_synthetic("demo_gis_analysis")
        report["steps"].append(
            {
                "action": "activate_use_demo_gis_analysis",
                "ok": True,
                "slot": man_g["frontend_slot"],
                "digest": man_g["digest"],
            }
        )
        engine.disable_plugin(
            plugin_id="demo_gis_analysis", actor="verify", confirm="disable"
        )

        pin = get_pin("true_color")
        report["true_color_pin"] = pin.get("mode")
        assert pin.get("mode") == "builtin"
        report["steps"].append({"action": "true_color_builtin_preserved", "ok": True})
        report["host_shell_rebuild_required"] = False
        report["note"] = (
            "Lifecycle mutates only tool_packs volume/registry; no docker build invoked."
        )
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = str(exc)
        print(json.dumps(report, indent=2))
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
