"""Imagery resolution band helpers and tool placement applicability."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.imagery_resolution import (
    BUILTIN_RESOLUTION_CATEGORY,
    category_implies_high_resolution,
    normalize_resolution_bands,
    normalize_resolution_category,
    normalize_satellite_names,
    resolution_band_options,
)
from app.database.base import Base
from app.models import tool_tree as tool_tree_models  # noqa: F401
from app.plugins import engine
from app.plugins.registry import load_registry
from app.services import tool_tree_service as svc
from app.services.tool_tree_service import ToolTreeError
from app.tools.pack_loader import verify_pack_at
from app.tools.pack_ops import ensure_default_pins
from app.tools.pack_signatures import generate_keypair, sign_digest, write_signature_file


def test_resolution_band_options_include_requested_labels():
    labels = {b["label"] for b in resolution_band_options()}
    for expected in ("≤1m", "≤2m", "≤3m", "≤5m", "≤10m", "≤15m", "≤30m", "<30m", ">30m"):
        assert expected in labels


def test_normalize_resolution_bands_orders_and_rejects_unknown():
    assert normalize_resolution_bands(["lte_30m", "lte_1m", "lte_1m"]) == ["lte_1m", "lte_30m"]
    with pytest.raises(ValueError, match="unknown resolution band"):
        normalize_resolution_bands(["lte_99m"])


def test_normalize_resolution_category_and_high_res_implication():
    assert normalize_resolution_category("lte_5m") == "lte_5m"
    assert normalize_resolution_category("") is None
    assert category_implies_high_resolution("lte_2m") is True
    assert category_implies_high_resolution("lte_10m") is False
    assert BUILTIN_RESOLUTION_CATEGORY["SENTINEL-2"] == "lte_10m"
    assert BUILTIN_RESOLUTION_CATEGORY["MODIS"] == "gt_30m"


def test_normalize_satellite_names():
    assert normalize_satellite_names(["sentinel-2", "SENTINEL-2", " landsat-9 "]) == [
        "SENTINEL-2",
        "LANDSAT-9",
    ]


@pytest.fixture
async def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "tool_packs"
    root.mkdir()
    (root / "artifacts").mkdir()
    (root / "publishers").mkdir()
    (root / "audit").mkdir()
    priv, pub = generate_keypair()
    (root / "publishers" / "approved_publishers.json").write_text(
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
    monkeypatch.setenv("EV_RUNTIME_PINS", str(root / "runtime_pins.json"))
    monkeypatch.setenv("EV_ARTIFACTS_ROOT", str(root / "artifacts"))
    monkeypatch.setenv("EV_PLUGIN_REGISTRY", str(root / "plugin_registry.json"))
    monkeypatch.setenv("EV_PACK_PUBLISHERS", str(root / "publishers" / "approved_publishers.json"))
    monkeypatch.setenv("EV_PACK_REQUIRE_SIGNATURE", "1")
    monkeypatch.setenv("EV_PACK_TRUST_PROFILE", "production")
    monkeypatch.setenv("EV_PACK_AUDIT_LOG", str(root / "audit" / "promotions.jsonl"))
    from app.tools import runtime_pins as rp

    rp._CACHE = {"mtime": None, "data": None}
    ensure_default_pins()
    load_registry(force=True)

    engine_db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tree.db'}")
    session_factory = async_sessionmaker(engine_db, class_=AsyncSession, expire_on_commit=False)
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = Path(__file__).resolve().parents[3]
    src = repo / "tools" / "plugins" / "demo_hello" / "artifacts" / "1.0.0"
    dest = tmp_path / "pack-hello"
    shutil.copytree(src, dest)
    meta = verify_pack_at(dest, "demo_hello", "1.0.0")
    sig = sign_digest(meta["digest"], priv)
    write_signature_file(dest, digest=meta["digest"], signature=sig, publisher_id="test-pub")
    zpath = tmp_path / "hello.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in dest.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(dest)))
    with zpath.open("rb") as fh:
        staging_id = engine.upload_stream(fh)
    validated = engine.validate_staging(staging_id)
    engine.install_from_staging(
        staging_id=staging_id,
        expected_digest=validated["digest"],
        actor="test",
        confirm="install",
    )

    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine_db.dispose()


@pytest.mark.asyncio
async def test_placement_stores_applicable_resolutions_and_satellites(db):
    session = db
    root = await svc.create_category(session, name="Detection", actor="admin")
    await session.commit()
    place = await svc.upsert_placement(
        session,
        plugin_id="demo_hello",
        category_id=root.id,
        display_name="Ship Detect",
        execution_slot="right_analysis_panel",
        applicable_resolutions=["lte_1m", "lte_2m", "lt_30m"],
        applicable_satellites=["WorldView-3", "SENTINEL-2"],
        actor="admin",
    )
    await session.commit()
    assert place.applicable_resolutions == ["lte_1m", "lte_2m", "lt_30m"]
    assert place.applicable_satellites == ["WORLDVIEW-3", "SENTINEL-2"]

    tree = await svc.build_tree(session, admin=True)
    assert tree["resolution_bands"]
    item = tree["roots"][0]["placements"][0]
    assert item["applicable_resolutions"] == ["lte_1m", "lte_2m", "lt_30m"]
    assert item["applicable_satellites"] == ["WORLDVIEW-3", "SENTINEL-2"]


@pytest.mark.asyncio
async def test_placement_rejects_unknown_resolution(db):
    session = db
    root = await svc.create_category(session, name="Bad", actor="admin")
    await session.commit()
    with pytest.raises(ToolTreeError, match="unknown resolution band"):
        await svc.upsert_placement(
            session,
            plugin_id="demo_hello",
            category_id=root.id,
            display_name="Nope",
            execution_slot="right_analysis_panel",
            applicable_resolutions=["lte_99m"],
            actor="admin",
        )
