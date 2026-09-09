"""Master health: HEALTHY / WARNING / CORRUPTED / MISSING / INCOMPLETE."""

from __future__ import annotations

from typing import Any

from app.master.objects import has_object, verify_object
from app.master.store import MasterStore
from app.master.tree import index_active

HEALTHY = "HEALTHY"
WARNING = "WARNING"
CORRUPTED = "CORRUPTED"
MISSING = "MISSING"
INCOMPLETE = "INCOMPLETE"


def assess_health(
    store: MasterStore,
    *,
    required_sources: list[str] | None = None,
    require_database: bool = False,
    deep: bool = False,
) -> dict[str, Any]:
    if not store.root.exists() or not store.has_head():
        return {"status": MISSING, "detail": "No master HEAD.", "generation": None}
    generation = store.head_generation()
    try:
        tree = store.load_tree(generation)
    except Exception as exc:  # noqa: BLE001
        return {"status": INCOMPLETE, "detail": str(exc), "generation": generation}
    files = index_active(tree)
    if not files:
        return {"status": INCOMPLETE, "detail": "Current tree has no ACTIVE files.", "generation": generation}
    missing_objects = []
    corrupt = []
    for record in files.values():
        digest = str(record.get("sha256") or "")
        if not digest or not has_object(store.objects_root, digest):
            missing_objects.append(digest or file_name(record))
        elif deep and not verify_object(store.objects_root, digest):
            corrupt.append(digest)
    if corrupt:
        return {"status": CORRUPTED, "detail": f"{len(corrupt)} object checksum mismatch(es).", "generation": generation}
    if missing_objects:
        return {
            "status": INCOMPLETE,
            "detail": f"{len(missing_objects)} referenced object(s) missing.",
            "generation": generation,
        }
    if required_sources:
        present_roots = {str(item.get("source_root") or "").rstrip("/") for item in files.values()}
        absent = [src for src in required_sources if src.rstrip("/") not in present_roots]
        if absent:
            return {
                "status": INCOMPLETE,
                "detail": "Required sources missing from tree: " + ", ".join(absent),
                "generation": generation,
            }
    meta = store.load_meta()
    meta_gen = meta.get("generation")
    if meta_gen not in {None, generation} and str(meta_gen) != str(generation):
        return {
            "status": WARNING,
            "detail": f"meta.json generation {meta_gen} does not match HEAD {generation}.",
            "generation": generation,
            "meta": meta,
        }
    db_ok = str(meta.get("database") or meta.get("database_status") or "").upper() in {"OK", "SKIPPED", "UNCHANGED", ""}
    if require_database and str(meta.get("database") or "").upper() not in {"OK", "UNCHANGED"}:
        return {"status": WARNING, "detail": "Database component is not verified.", "generation": generation, "meta": meta}
    if meta.get("integrity") not in {None, "OK", "ok"}:
        return {"status": WARNING, "detail": str(meta.get("integrity")), "generation": generation, "meta": meta}
    if not db_ok and require_database:
        return {"status": WARNING, "detail": "Database status unknown.", "generation": generation, "meta": meta}
    return {
        "status": HEALTHY,
        "detail": "Master backup is healthy.",
        "generation": generation,
        "files": len(files),
        "meta": meta,
    }


def file_name(record: dict[str, Any]) -> str:
    return f"{record.get('source_root')}/{record.get('relative_path')}"
