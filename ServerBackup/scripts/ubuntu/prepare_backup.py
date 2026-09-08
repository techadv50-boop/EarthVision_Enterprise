#!/usr/bin/env python3
"""Ubuntu-side backup preparation. Read-only against production data."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from pathlib import Path

ALLOWED_ACTIONS = {
    "check",
    "discover-databases",
    "backup",
    "cleanup",
    "dry-run",
    "discover-ojs",
    "inventory",
    "hash-files",
    "stream-objects",
    "database-fingerprint",
    "dump-databases",
}
SYSTEM_DATABASES = {"information_schema", "performance_schema", "mysql", "sys"}
UNSAFE = set(';&|`$<>\\\n\r')


def fail(message: str, code: int = 1) -> None:
    # Never mix JSON errors into a streamed tar.gz on stdout.
    sys.stderr.write(message + "\n")
    if sys.stdout.isatty() or action_is_json():
        json.dump({"ok": False, "error": message}, sys.stdout)
        sys.stdout.write("\n")
    raise SystemExit(code)


def action_is_json() -> bool:
    return os.environ.get("SERVERBACKUP_STREAM") != "1"


def safe_unix(path: str) -> str:
    if not path or not path.startswith("/") or ".." in path or any(ch in path for ch in UNSAFE):
        fail(f"Refusing unsafe path: {path!r}")
    return path.rstrip("/") or "/"


def load_payload(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        fail("Invalid payload")
    return data


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)


def mysql_defaults() -> list[str]:
    cnf = Path("/etc/serverbackup/my.cnf")
    if cnf.is_file():
        return [f"--defaults-extra-file={cnf}"]
    return []


def discover_databases() -> list[str]:
    mysqldump = shutil.which("mysqldump")
    mysql = shutil.which("mysql")
    if not mysql:
        fail("mysql client was not found")
    cmd = ["mysql", *mysql_defaults(), "--batch", "--skip-column-names", "-e", "SHOW DATABASES"]
    result = run(cmd, timeout=60)
    if result.returncode != 0:
        fail(result.stderr.strip() or "SHOW DATABASES failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def df_gb(path: str = "/tmp") -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


def path_checks(payload: dict) -> list[dict]:
    checks = []
    for label, path in [
        *[(f"website {p}", p) for p in payload.get("website_directories") or []],
        *[
            (f"OJS private files {p}", p)
            for p in (payload.get("ojs_private_directories") or ([payload["ojs_private_files"]] if payload.get("ojs_private_files") else []))
        ],
        ("Nginx", payload.get("nginx_directory") or ""),
        *[(f"extra {p}", p) for p in payload.get("extra_directories") or []],
    ]:
        if not path:
            checks.append({"name": label, "ok": False, "detail": "path not set"})
            continue
        safe = safe_unix(str(path))
        ok = os.path.isdir(safe)
        checks.append({"name": label, "ok": ok, "detail": safe if ok else f"missing: {safe}"})
    mariadb_ok = shutil.which("mysqldump") is not None and shutil.which("mysql") is not None
    checks.append({"name": "MariaDB client", "ok": mariadb_ok, "detail": "mysqldump/mysql"})
    tar_ok = shutil.which("tar") is not None and shutil.which("gzip") is not None
    checks.append({"name": "tar/gzip", "ok": tar_ok, "detail": "present" if tar_ok else "missing"})
    return checks


def dump_databases(work: Path, names: list[str], compression_level: int) -> list[str]:
    dumped: list[str] = []
    dest = work / "databases"
    dest.mkdir(parents=True, exist_ok=True)
    mysqldump = shutil.which("mysqldump")
    if not mysqldump:
        fail("mysqldump was not found")
    for name in names:
        if any(ch in name for ch in UNSAFE) or "/" in name or " " in name:
            fail(f"Refusing unsafe database name: {name!r}")
        out = dest / f"{name}.sql.gz"
        args = [
            mysqldump,
            *mysql_defaults(),
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--events",
            "--hex-blob",
            "--databases",
            name,
        ]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        with gzip.open(out, "wb", compresslevel=compression_level) as handle:
            while True:
                chunk = proc.stdout.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
        if proc.wait() != 0:
            fail(stderr.strip() or f"mysqldump failed for {name}")
        dumped.append(name)
    return dumped


def add_tree(archive: tarfile.TarFile, source: str, arcname: str) -> None:
    path = Path(source)
    if not path.exists():
        fail(f"Missing path: {source}")
    archive.add(path, arcname=arcname, recursive=True, filter=_safe_filter)


def _safe_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = tarinfo.name
    if name.endswith("/.git") or "/.git/" in f"/{name}/":
        return None
    return tarinfo


def stream_backup(payload: dict) -> None:
    work_id = "".join(ch for ch in str(payload.get("work_id") or "work") if ch.isalnum() or ch in "-_")
    work = Path("/tmp") / f"server-backup-work-{work_id}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    compression = int(payload.get("compression_level") or 6)
    websites = [safe_unix(p) for p in payload.get("website_directories") or []]
    extra = [safe_unix(p) for p in payload.get("extra_directories") or []]
    ojs_dirs = [safe_unix(p) for p in payload.get("ojs_private_directories") or []]
    if not ojs_dirs and payload.get("ojs_private_files"):
        ojs_dirs = [safe_unix(str(payload.get("ojs_private_files")))]
    if not ojs_dirs:
        fail("No OJS files_dir provided; refusing silent fallback to /var/www/ojs-files")
    nginx = safe_unix(str(payload.get("nginx_directory") or "/etc/nginx"))
    databases = list(payload.get("databases") or [])
    dumped = dump_databases(work, databases, compression) if databases else []
    manifest = {
        "hostname": socket.gethostname(),
        "websites": websites,
        "ojs_private_directories": ojs_dirs,
        "nginx": nginx,
        "extra": extra,
        "databases": dumped,
    }
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    gzip_file = gzip.open(sys.stdout.buffer, "wb", compresslevel=compression)
    with tarfile.open(fileobj=gzip_file, mode="w|") as archive:
        archive.add(work / "manifest.json", arcname="manifest.json")
        if dumped:
            archive.add(work / "databases", arcname="databases", recursive=True)
        for path in websites:
            archive.add(path, arcname=f"websites/{Path(path).name}", recursive=True, filter=_safe_filter)
        for ojs in ojs_dirs:
            archive.add(ojs, arcname=f"ojs/{Path(ojs).name}", recursive=True, filter=_safe_filter)
        archive.add(nginx, arcname="nginx", recursive=True, filter=_safe_filter)
        for path in extra:
            archive.add(path, arcname=f"extra/{Path(path).name}", recursive=True, filter=_safe_filter)
    gzip_file.close()
    # Keep work dir until Windows confirms; cleanup action removes it.


def main() -> None:
    if len(sys.argv) < 2:
        fail("payload path required")
    payload = load_payload(sys.argv[1])
    action = str(payload.get("action") or "")
    if action not in ALLOWED_ACTIONS:
        fail("action not allowed")
    if action == "discover-databases":
        names = discover_databases()
        json.dump({"ok": True, "databases": names}, sys.stdout)
        sys.stdout.write("\n")
        return
    if action == "cleanup":
        work_id = "".join(ch for ch in str(payload.get("work_id") or "") if ch.isalnum() or ch in "-_")
        if not work_id:
            fail("work_id required")
        work = Path("/tmp") / f"server-backup-work-{work_id}"
        if work.is_dir():
            shutil.rmtree(work)
        json.dump({"ok": True, "removed": str(work)}, sys.stdout)
        sys.stdout.write("\n")
        return
    if action in {"discover-ojs", "inventory", "hash-files", "stream-objects", "database-fingerprint"}:
        from prepare_master import handle as handle_master

        result = handle_master(action, payload, run=run, mysql_defaults=mysql_defaults)
        if result is None:
            return
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        if not result.get("ok"):
            raise SystemExit(1)
        return
    if action == "dump-databases":
        work_id = "".join(ch for ch in str(payload.get("work_id") or "work") if ch.isalnum() or ch in "-_")
        work = Path("/tmp") / f"server-backup-work-{work_id}"
        work.mkdir(parents=True, exist_ok=True)
        dumped = dump_databases(work, list(payload.get("databases") or []), int(payload.get("compression_level") or 6))
        files = []
        for name in dumped:
            path = work / "databases" / f"{name}.sql.gz"
            files.append({"name": name, "path": str(path), "size": path.stat().st_size if path.is_file() else 0})
        json.dump({"ok": True, "dumps": files}, sys.stdout)
        sys.stdout.write("\n")
        return
    if action in {"check", "dry-run"}:
        checks = path_checks(payload)
        free = df_gb("/tmp")
        min_free = float(payload.get("min_free_disk_gb") or 0)
        space_ok = free >= min_free
        checks.append({"name": "Ubuntu /tmp free space", "ok": space_ok, "detail": f"{free:.1f} GB"})
        mariadb_ping = run(["mysqladmin", *mysql_defaults(), "ping"], timeout=20)
        checks.append(
            {
                "name": "MariaDB ping",
                "ok": mariadb_ping.returncode == 0,
                "detail": (mariadb_ping.stdout or mariadb_ping.stderr or "").strip(),
            }
        )
        ok = all(item["ok"] for item in checks)
        json.dump(
            {
                "ok": ok,
                "hostname": socket.gethostname(),
                "free_gb": round(free, 2),
                "checks": checks,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        if action == "check" and not ok:
            raise SystemExit(1)
        return
    if action == "backup":
        os.environ["SERVERBACKUP_STREAM"] = "1"
        stream_backup(payload)
        return
    fail("unhandled action")


if __name__ == "__main__":
    main()
