"""Plugin-first tool category tree tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.models import tool_tree as tool_tree_models  # noqa: F401
from app.plugins import engine
from app.plugins.registry import load_registry
from app.services import tool_tree_service as svc
from app.services.tool_tree_service import ToolTreeError
from app.tools.pack_ops import ensure_default_pins
from app.tools.pack_signatures import generate_keypair, sign_digest, write_signature_file
from app.tools.pack_loader import verify_pack_at
import zipfile


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

    # Install demo_hello for placement tests
    repo = Path(__file__).resolve().parents[3]
    src = repo / "tools" / "plugins" / "demo_hello" / "artifacts" / "1.0.0"
    dest = tmp_path / "pack-hello"
    import shutil

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
        yield session, priv
        await session.rollback()
    await engine_db.dispose()


@pytest.mark.asyncio
async def test_empty_tree_message(db):
    session, _ = db
    tree = await svc.build_tree(session, admin=False)
    assert tree["empty"] is True
    assert "No tools installed" in (tree["message"] or "")


@pytest.mark.asyncio
async def test_category_nesting_place_activate_and_disable(db):
    session, _ = db
    root = await svc.create_category(session, name="Image Processing", actor="admin")
    sub = await svc.create_category(
        session, name="Enhancement", parent_id=root.id, actor="admin"
    )
    await session.commit()

    place = await svc.upsert_placement(
        session,
        plugin_id="demo_hello",
        category_id=sub.id,
        display_name="Contrast Demo",
        execution_slot="right_analysis_panel",
        actor="admin",
    )
    await session.commit()

    # Not active yet — user tree still empty of this tool
    tree = await svc.build_tree(session, admin=False)
    assert tree["empty"] is True

    engine.activate_plugin(
        plugin_id="demo_hello", version="1.0.0", actor="admin", confirm="activate"
    )
    tree = await svc.build_tree(session, admin=False)
    assert tree["empty"] is False
    assert tree["roots"][0]["name"] == "Image Processing"
    assert tree["roots"][0]["children"][0]["name"] == "Enhancement"
    assert tree["roots"][0]["children"][0]["placements"][0]["display_name"] == "Contrast Demo"

    slot_items = await svc.active_for_slot(session, "right_analysis_panel")
    assert any(i["plugin_id"] == "demo_hello" for i in slot_items)

    engine.disable_plugin(plugin_id="demo_hello", actor="admin", confirm="disable")
    tree2 = await svc.build_tree(session, admin=False)
    assert tree2["empty"] is True


@pytest.mark.asyncio
async def test_cannot_delete_category_with_tools(db):
    session, _ = db
    root = await svc.create_category(session, name="Airfield", actor="admin")
    await svc.upsert_placement(
        session,
        plugin_id="demo_hello",
        category_id=root.id,
        display_name="Runway Demo",
        execution_slot="right_analysis_panel",
        actor="admin",
    )
    await session.commit()
    with pytest.raises(ToolTreeError, match="containing tools"):
        await svc.delete_category(session, root.id, actor="admin")


@pytest.mark.asyncio
async def test_circular_move_prevented(db):
    session, _ = db
    a = await svc.create_category(session, name="A", actor="admin")
    b = await svc.create_category(session, name="B", parent_id=a.id, actor="admin")
    await session.commit()
    with pytest.raises(ToolTreeError, match="circular"):
        await svc.move_category(session, a.id, parent_id=b.id, actor="admin")


@pytest.mark.asyncio
async def test_reorder_categories_and_tools(db):
    session, _ = db
    c1 = await svc.create_category(session, name="Zulu", actor="admin")
    c2 = await svc.create_category(session, name="Alpha", actor="admin")
    await session.commit()
    await svc.reorder_categories(session, [c2.id, c1.id], parent_id=None, actor="admin")
    await session.commit()
    tree = await svc.build_tree(session, admin=True)
    assert [r["name"] for r in tree["roots"]] == ["Alpha", "Zulu"]
