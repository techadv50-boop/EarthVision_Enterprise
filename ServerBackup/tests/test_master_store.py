import hashlib
from pathlib import Path

from app.master.delta import compute_delta, next_tree_files
from app.master.health import CORRUPTED, HEALTHY, INCOMPLETE, MISSING, assess_health
from app.master.objects import object_path, write_object_from_bytes
from app.master.store import MasterError, MasterStore
from app.master.tree import make_record


def _inv(root: str, rel: str, content: bytes, mtime: int = 1) -> dict:
    return {
        "source_root": root,
        "relative_path": rel,
        "size": len(content),
        "mtime": mtime,
        "mode": 0o644,
        "uid": 0,
        "gid": 0,
        "inode": 1,
        "category": "website",
        "sha256": hashlib.sha256(content).hexdigest(),
        "absolute_path": f"{root}/{rel}",
    }


def test_store_commit_is_atomic_and_head_is_last(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    digest = write_object_from_bytes(store.objects_root, b"hello")
    rec = make_record(source_root="/var/www/a", relative_path="index.html", sha256=digest, size=5)
    store.commit(
        generation=1,
        tree={"files": [rec]},
        meta={"generation": 1, "database": "SKIPPED", "integrity": "OK"},
        history={"operation_id": "op1", "type": "FULL", "status": "SUCCESS"},
    )
    assert store.head_generation() == 1
    assert store.load_tree()["generation"] == 1
    health = assess_health(store, deep=True)
    assert health["status"] == HEALTHY


def test_failed_commit_does_not_advance_head(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    rec = make_record(source_root="/var/www/a", relative_path="x", sha256="ab" * 32, size=1)
    try:
        store.commit(
            generation=1,
            tree={"files": [rec]},
            meta={"generation": 1},
            history={"operation_id": "bad"},
        )
        assert False, "commit should fail"
    except MasterError:
        pass
    assert store.head_generation() is None
    assert not store.has_head()


def test_corrupted_object_is_detected(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    digest = write_object_from_bytes(store.objects_root, b"good")
    rec = make_record(source_root="/var/www/a", relative_path="f", sha256=digest, size=4)
    store.commit(
        generation=1,
        tree={"files": [rec]},
        meta={"generation": 1, "database": "SKIPPED", "integrity": "OK"},
        history={"operation_id": "op1", "type": "FULL"},
    )
    object_path(store.objects_root, digest).write_bytes(b"evil")
    health = assess_health(store, deep=True)
    assert health["status"] == CORRUPTED


def test_corrupted_tree_is_incomplete(tmp_path: Path):
    store = MasterStore(tmp_path / "ServerBackups")
    digest = write_object_from_bytes(store.objects_root, b"good")
    rec = make_record(source_root="/var/www/a", relative_path="f", sha256=digest, size=4)
    store.commit(
        generation=1,
        tree={"files": [rec]},
        meta={"generation": 1, "database": "SKIPPED", "integrity": "OK"},
        history={"operation_id": "op1", "type": "FULL"},
    )
    (store.trees_dir / "1.json").write_text("{not json", encoding="utf-8")
    health = assess_health(store, deep=False)
    assert health["status"] == INCOMPLETE


def test_missing_master():
    store = MasterStore("/tmp/does-not-exist-master-140")
    assert assess_health(store)["status"] == MISSING


def test_delta_new_modified_deleted_renamed_moved():
    root = "/var/www/site"
    other = "/var/www/other"
    a = _inv(root, "a.txt", b"aaa")
    b = _inv(root, "b.txt", b"bbb")
    first = compute_delta(None, [a, b], hashes={})
    assert first.new or first.hash_candidates or first.transfer
    tree = {"files": next_tree_files(compute_delta(None, [a, b], hashes={k: v["sha256"] for k, v in {
        f"{root}/a.txt": a, f"{root}/b.txt": b
    }.items()}), generation=1, timestamp="t")}
    # Wait, easier: build previous tree from records
    prev = {
        "files": [
            {**a, "state": "ACTIVE", "first_seen": "t0"},
            {**b, "state": "ACTIVE", "first_seen": "t0"},
        ]
    }
    hashes = {
        f"{root}/a.txt": a["sha256"],
        f"{root}/renamed.txt": b["sha256"],
        f"{other}/moved.txt": a["sha256"],
        f"{root}/c.txt": hashlib.sha256(b"ccc").hexdigest(),
    }
    inventory = [
        _inv(root, "a.txt", b"AAA", mtime=9),  # modified
        _inv(root, "renamed.txt", b"bbb"),  # renamed from b.txt
        _inv(other, "moved.txt", b"aaa"),  # this would conflict with a.txt hash unique
        _inv(root, "c.txt", b"ccc"),  # new
    ]
    # Unique hash: a modified so old a hash gone; moved.txt has old a hash - but a.txt still exists with new hash
    # b.txt deleted, renamed.txt has b hash -> RENAMED
    # no moved unique if a still exists
    changes = compute_delta(prev, inventory, hashes={
        f"{root}/a.txt": hashlib.sha256(b"AAA").hexdigest(),
        f"{root}/renamed.txt": b["sha256"],
        f"{other}/moved.txt": hashlib.sha256(b"moved").hexdigest(),
        f"{root}/c.txt": hashlib.sha256(b"ccc").hexdigest(),
    })
    assert len(changes.modified) == 1
    assert len(changes.renamed) == 1
    assert changes.renamed[0]["change_kind"] == "RENAMED"
    assert len(changes.new) == 2
    assert len(changes.deleted) == 0
    # Move: delete a.txt and add other/moved.txt with same hash
    prev2 = {"files": [{**a, "state": "ACTIVE"}]}
    inv2 = [_inv(other, "moved.txt", b"aaa")]
    moved = compute_delta(prev2, inv2, hashes={f"{other}/moved.txt": a["sha256"]})
    assert len(moved.moved) == 1
    assert moved.moved[0]["change_kind"] == "MOVED"
    assert moved.empty is False


def test_metadata_same_hash_is_no_change():
    root = "/var/www/site"
    rec = _inv(root, "a.txt", b"same", mtime=1)
    prev = {"files": [{**rec, "state": "ACTIVE"}]}
    later = _inv(root, "a.txt", b"same", mtime=99)
    changes = compute_delta(prev, [later], hashes={f"{root}/a.txt": rec["sha256"]})
    assert changes.empty
    assert changes.unchanged


def test_no_keep_five_on_master_directory(tmp_path: Path):
    from app.backup.retention import apply_retention, list_successful_backups
    from tests.helpers import write_success_backup

    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    (dest / "master").mkdir()
    (dest / "master" / "HEAD").write_text("1\n", encoding="utf-8")
    for i in range(1, 6):
        write_success_backup(dest, f"2026-09-0{i}_010000")
    removed = apply_retention(dest, keep=5)
    assert removed == []
    assert (dest / "master" / "HEAD").is_file()
    assert len(list_successful_backups(dest)) == 5
