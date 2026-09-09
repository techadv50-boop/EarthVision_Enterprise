"""Delta detection: NEW, MODIFIED, DELETED, RENAMED, MOVED. Metadata first."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.master.tree import STATE_ACTIVE, STATE_DELETED, STATE_RENAMED, file_key, index_active


@dataclass
class ChangeSet:
    new: list[dict[str, Any]] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[dict[str, Any]] = field(default_factory=list)
    renamed: list[dict[str, Any]] = field(default_factory=list)
    moved: list[dict[str, Any]] = field(default_factory=list)
    unchanged: list[dict[str, Any]] = field(default_factory=list)
    hash_candidates: list[dict[str, Any]] = field(default_factory=list)
    transfer: list[dict[str, Any]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.new or self.modified or self.deleted or self.renamed or self.moved)

    def counts(self) -> dict[str, int]:
        return {
            "new": len(self.new),
            "modified": len(self.modified),
            "deleted": len(self.deleted),
            "renamed": len(self.renamed),
            "moved": len(self.moved),
            "unchanged": len(self.unchanged),
        }

    def estimated_transfer_bytes(self) -> int:
        return int(sum(int(item.get("size") or 0) for item in self.transfer))


def promote_unhashed_for_preview(changes: ChangeSet) -> ChangeSet:
    """Classify unhashed candidates using metadata only. DRY RUN never SHA-256s the live tree.

    New paths without a digest become NEW. Existing paths whose size/mtime/mode
    changed become MODIFIED. Rename/move detection requires hashes and is left
    to BACKUP NOW.
    """
    for item in changes.hash_candidates:
        rec = dict(item)
        if rec.get("previous_sha256"):
            changes.modified.append(rec)
        else:
            changes.new.append(rec)
        changes.transfer.append(rec)
    changes.hash_candidates.clear()
    return changes


def _meta_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for field_name in ("size", "mtime", "mode", "uid", "gid"):
        if int(left.get(field_name) or 0) != int(right.get(field_name) or 0):
            return False
    return True


def _copy_active(prev: dict[str, Any], inv: dict[str, Any], digest: str | None) -> dict[str, Any]:
    rec = dict(prev)
    rec.update({k: inv.get(k) for k in ("size", "mtime", "mode", "uid", "gid", "inode", "category", "absolute_path")})
    rec["state"] = STATE_ACTIVE
    rec["sha256"] = digest or prev.get("sha256")
    rec["source_root"] = inv.get("source_root") or prev.get("source_root")
    rec["relative_path"] = inv.get("relative_path") or prev.get("relative_path")
    rec["first_seen"] = prev.get("first_seen")
    return rec


def compute_delta(
    previous_tree: dict[str, Any] | None,
    inventory: list[dict[str, Any]],
    *,
    hashes: dict[str, str] | None = None,
) -> ChangeSet:
    """Compare inventory to the last ACTIVE tree. hashes maps file_key -> sha256."""
    hashes = {k: v.lower() for k, v in (hashes or {}).items()}
    previous = index_active(previous_tree or {})
    current = {
        file_key(str(item.get("source_root") or ""), str(item.get("relative_path") or "")): item
        for item in inventory
    }
    changes = ChangeSet()
    new_keys = [key for key in current if key not in previous]
    deleted_keys = [key for key in previous if key not in current]
    shared = [key for key in current if key in previous]

    for key in shared:
        inv = current[key]
        prev = previous[key]
        digest = hashes.get(key) or (str(inv.get("sha256") or "").lower() or None)
        prev_digest = str(prev.get("sha256") or "").lower()
        if digest and prev_digest and digest == prev_digest:
            changes.unchanged.append(_copy_active(prev, inv, digest))
            continue
        if _meta_equal(inv, prev) and not digest:
            changes.unchanged.append(_copy_active(prev, inv, prev_digest or None))
            continue
        candidate = dict(inv)
        candidate["previous_sha256"] = prev.get("sha256")
        candidate["old_path"] = key
        candidate["first_seen"] = prev.get("first_seen")
        if not digest:
            changes.hash_candidates.append(candidate)
            continue
        rec = dict(inv)
        rec["sha256"] = digest
        rec["state"] = STATE_ACTIVE
        rec["previous_sha256"] = prev.get("sha256")
        rec["first_seen"] = prev.get("first_seen")
        changes.modified.append(rec)
        changes.transfer.append(rec)

    pending_new = []
    for key in new_keys:
        item = dict(current[key])
        item["state"] = STATE_ACTIVE
        digest = hashes.get(key) or (str(item.get("sha256") or "").lower() or None)
        if digest:
            item["sha256"] = digest
        pending_new.append((key, item))

    deleted_by_hash: dict[str, list[str]] = {}
    for key in deleted_keys:
        digest = str(previous[key].get("sha256") or "").lower()
        if digest:
            deleted_by_hash.setdefault(digest, []).append(key)

    consumed_deleted: set[str] = set()
    for key, item in pending_new:
        digest = str(item.get("sha256") or "").lower()
        matches = deleted_by_hash.get(digest) or []
        unique = [old for old in matches if old not in consumed_deleted]
        if digest and len(unique) == 1:
            old_key = unique[0]
            old_rec = previous[old_key]
            renamed = dict(item)
            renamed["sha256"] = digest
            renamed["old_path"] = old_key
            renamed["first_seen"] = old_rec.get("first_seen")
            same_root = str(old_rec.get("source_root") or "").rstrip("/") == str(item.get("source_root") or "").rstrip("/")
            if same_root:
                renamed["state"] = STATE_RENAMED
                renamed["change_kind"] = "RENAMED"
                changes.renamed.append(renamed)
            else:
                renamed["state"] = STATE_RENAMED
                renamed["change_kind"] = "MOVED"
                changes.moved.append(renamed)
            consumed_deleted.add(old_key)
            continue
        if not digest:
            changes.hash_candidates.append(item)
        else:
            changes.new.append(item)
            changes.transfer.append(item)

    for key in deleted_keys:
        if key in consumed_deleted:
            continue
        rec = dict(previous[key])
        rec["state"] = STATE_DELETED
        rec["old_path"] = key
        rec["change_kind"] = "DELETED"
        changes.deleted.append(rec)

    return changes


def next_tree_files(changes: ChangeSet, *, generation: int, timestamp: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in changes.unchanged + changes.modified + changes.new + changes.renamed + changes.moved:
        rec = dict(item)
        rec["state"] = STATE_ACTIVE
        rec["generation"] = generation
        rec["last_seen"] = timestamp
        rec["first_seen"] = rec.get("first_seen") or timestamp
        rec["type"] = rec.get("type") or rec.get("file_type") or "file"
        files.append(rec)
    return files
