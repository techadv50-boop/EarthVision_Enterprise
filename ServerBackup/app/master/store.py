"""On-disk master store. HEAD is only replaced after full verification."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.master.objects import has_object, object_path, verify_object, write_object_from_file
from app.master.tree import index_active

HEAD_NAME = "HEAD"
META_NAME = "meta.json"


class MasterError(RuntimeError):
    pass


class MasterStore:
    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination)
        self.root = self.destination / "master"
        self.objects_root = self.root
        self.trees_dir = self.root / "trees"
        self.history_dir = self.root / "history"
        self.staging_dir = self.root / "staging"
        self.head_path = self.root / HEAD_NAME
        self.meta_path = self.root / META_NAME

    def ensure_layout(self) -> None:
        for path in (self.root, self.root / "objects", self.trees_dir, self.history_dir, self.staging_dir):
            path.mkdir(parents=True, exist_ok=True)

    def has_head(self) -> bool:
        return self.head_path.is_file() and bool(self.head_generation())

    def head_generation(self) -> int | None:
        if not self.head_path.is_file():
            return None
        text = self.head_path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        try:
            return int(text.split()[0])
        except ValueError:
            return None

    def load_meta(self) -> dict[str, Any]:
        if not self.meta_path.is_file():
            return {}
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def load_tree(self, generation: int | None = None) -> dict[str, Any]:
        gen = self.head_generation() if generation is None else generation
        if gen is None:
            return {"generation": 0, "files": []}
        path = self.trees_dir / f"{gen}.json"
        if not path.is_file():
            raise MasterError(f"Master tree for generation {gen} is missing.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MasterError(f"Master tree for generation {gen} is unreadable.") from exc
        if not isinstance(data, dict):
            raise MasterError(f"Master tree for generation {gen} is invalid.")
        return data

    def list_history(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.history_dir.is_dir():
            return rows
        for path in sorted(self.history_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                rows.append(data)
        return rows

    def begin_staging(self, operation_id: str) -> Path:
        self.ensure_layout()
        path = self.staging_dir / operation_id
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_staging(self, operation_id: str | None = None) -> None:
        if operation_id:
            path = self.staging_dir / operation_id
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            return
        if self.staging_dir.is_dir():
            for child in self.staging_dir.iterdir():
                shutil.rmtree(child, ignore_errors=True)

    def put_file_object(self, source: Path, *, expected: str | None = None) -> str:
        self.ensure_layout()
        return write_object_from_file(self.objects_root, source, expected=expected)

    def object_exists(self, digest: str) -> bool:
        return has_object(self.objects_root, digest)

    def object_file(self, digest: str) -> Path:
        return object_path(self.objects_root, digest)

    def verify_tree_objects(self, tree: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for record in index_active(tree).values():
            digest = str(record.get("sha256") or "")
            if not digest:
                missing.append(file_label(record) + " (no sha256)")
                continue
            if not verify_object(self.objects_root, digest):
                missing.append(file_label(record))
        return missing

    def _atomic_write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload, indent=2) + "\n"
            tmp.write_text(text, encoding="utf-8")
        else:
            tmp.write_text(str(payload).rstrip() + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def commit(
        self,
        *,
        generation: int,
        tree: dict[str, Any],
        meta: dict[str, Any],
        history: dict[str, Any],
    ) -> None:
        """Write tree/meta/history first. HEAD is last. Crash before HEAD keeps the old master."""
        self.ensure_layout()
        errors = self.verify_tree_objects(tree)
        if errors:
            raise MasterError("Cannot commit master: missing or corrupt objects: " + "; ".join(errors[:8]))
        op_id = str(history.get("operation_id") or uuid.uuid4().hex)
        history = dict(history)
        history["operation_id"] = op_id
        tree = dict(tree)
        tree["generation"] = generation
        self._atomic_write(self.trees_dir / f"{generation}.json", tree)
        self._atomic_write(self.history_dir / f"{op_id}.json", history)
        self._atomic_write(self.meta_path, meta)
        self._atomic_write(self.head_path, str(generation))

    def write_history_only(self, history: dict[str, Any]) -> None:
        self.ensure_layout()
        op_id = str(history.get("operation_id") or uuid.uuid4().hex)
        history = dict(history)
        history["operation_id"] = op_id
        self._atomic_write(self.history_dir / f"{op_id}.json", history)


def file_label(record: dict[str, Any]) -> str:
    return f"{record.get('source_root')}/{record.get('relative_path')}"


def master_dir_for(destination: str | Path) -> Path:
    return Path(destination) / "master"
