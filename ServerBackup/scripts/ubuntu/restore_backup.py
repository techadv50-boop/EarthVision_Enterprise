#!/usr/bin/env python3
"""Confirmed restore helper. Does not restart Nginx. Creates safety copies first."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from path_safety import require_unix_syntax

ALLOWED = {
    "restore-files",
    "restore-database",
    "restore-nginx",
    "restore-complete",
    "restore-master",
    "nginx-test",
    "safety-dump",
}
UNSAFE = set(';&|`$<>\\\n\r')


def fail(message: str) -> None:
    json.dump({"ok": False, "error": message}, sys.stdout)
    sys.stdout.write("\n")
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def safe_unix(path: str) -> str:
    try:
        return require_unix_syntax(path)
    except ValueError:
        fail(f"Refusing unsafe path: {path!r}")
    return "/"


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        fail("Invalid payload")
    return data


def mysql_defaults() -> list[str]:
    cnf = Path("/etc/serverbackup/my.cnf")
    if cnf.is_file():
        return [f"--defaults-extra-file={cnf}"]
    return []


def safety_root() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path("/var/backups/serverbackup-safety") / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_tree(src: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dest, dirs_exist_ok=True)
    elif os.path.isfile(src):
        shutil.copy2(src, dest)


def nginx_test() -> None:
    nginx = shutil.which("nginx")
    if not nginx:
        fail("nginx binary not found")
    result = subprocess.run([nginx, "-t"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        fail((result.stderr or result.stdout or "nginx -t failed").strip())


def restore_files(archive: tarfile.TarFile, target: str, prefix: str) -> None:
    members = [m for m in archive.getmembers() if m.name == prefix or m.name.startswith(prefix + "/")]
    if not members:
        fail(f"No archive members for {prefix}")
    safety = safety_root() / Path(target).name
    if os.path.exists(target):
        copy_tree(target, safety)
    dest = Path(target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for member in members:
        rel = member.name[len(prefix) :].lstrip("/")
        out = dest / rel if rel else dest
        if member.isdir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        with extracted, open(out, "wb") as handle:
            shutil.copyfileobj(extracted, handle)


def restore_database(archive: tarfile.TarFile, name: str) -> None:
    member_name = f"databases/{name}.sql.gz"
    try:
        member = archive.getmember(member_name)
    except KeyError:
        fail(f"Database dump not in archive: {name}")
    safety = safety_root() / f"{name}.sql.gz"
    mysqldump = shutil.which("mysqldump")
    mysql = shutil.which("mysql")
    if not mysqldump or not mysql:
        fail("mysql/mysqldump not found")
    dump = subprocess.run(
        [mysqldump, *mysql_defaults(), "--single-transaction", "--routines", "--triggers", "--events", "--databases", name],
        capture_output=True,
        check=False,
    )
    if dump.returncode == 0:
        import gzip

        with gzip.open(safety, "wb") as handle:
            handle.write(dump.stdout)
    extracted = archive.extractfile(member)
    if extracted is None:
        fail("Could not read database dump")
    import gzip

    sql = gzip.GzipFile(fileobj=extracted)
    restore = subprocess.run(
        [mysql, *mysql_defaults(), "--batch"],
        stdin=sql,
        capture_output=True,
        check=False,
    )
    if restore.returncode != 0:
        fail((restore.stderr or restore.stdout or b"mysql restore failed").decode("utf-8", "replace"))


def main() -> None:
    payload = load(sys.argv[1])
    action = str(payload.get("action") or "")
    if action not in ALLOWED:
        fail("action not allowed")
    if action == "restore-master":
        from restore_master import apply_pack

        result = apply_pack(payload)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return
    archive_path = safe_unix(str(payload.get("archive_path") or ""))
    if action == "nginx-test":
        nginx_test()
        json.dump({"ok": True, "nginx_test": True}, sys.stdout)
        sys.stdout.write("\n")
        return
    if not os.path.isfile(archive_path):
        fail(f"Archive not found: {archive_path}")
    with tarfile.open(archive_path, "r:*") as archive:
        if action in {"restore-files", "restore-complete"}:
            targets = payload.get("target_path")
            websites = [payload["target_path"]] if targets else list(payload.get("website_directories") or [])
            for path in websites:
                safe = safe_unix(path)
                restore_files(archive, safe, f"websites/{Path(safe).name}")
            ojs = str(payload.get("ojs_private_files") or "")
            if ojs and action == "restore-complete":
                restore_files(archive, safe_unix(ojs), f"ojs/{Path(ojs).name}")
        if action in {"restore-database", "restore-complete"}:
            for name in payload.get("databases") or []:
                if any(ch in name for ch in UNSAFE):
                    fail(f"Unsafe database name: {name!r}")
                restore_database(archive, name)
        if action in {"restore-nginx", "restore-complete"}:
            nginx_dir = safe_unix(str(payload.get("nginx_directory") or "/etc/nginx"))
            restore_files(archive, nginx_dir, "nginx")
            nginx_test()
            # Intentionally do not reload or restart Nginx.
    json.dump(
        {
            "ok": True,
            "action": action,
            "nginx_restarted": False,
            "message": "Restore completed. Nginx was not restarted.",
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
