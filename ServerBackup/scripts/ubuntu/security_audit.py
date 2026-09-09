#!/usr/bin/env python3
"""On-demand Ubuntu security audit. Default action is read-only.

Does not walk /, does not hash entire website trees, does not stop services.
Write actions are limited to /etc/serverbackup/.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from path_safety import require_unix_syntax

ALLOWED = {"security-audit", "security-rotate-token", "security-rollback"}
UNSAFE = set(';&|`$<>\\\n\r')
SKIP_DIR_NAMES = {
    "cache",
    "tmp",
    "temp",
    "sessions",
    "session",
    "node_modules",
    ".git",
    "__pycache__",
    "vendor",
}
CRITICAL_FILES = [
    "/etc/ssh/sshd_config",
    "/etc/nginx/nginx.conf",
    "/etc/sudoers",
]
MODE_LIMITS = {
    "LOW": {"max_files": 1200, "max_hash": 40, "max_bytes": 256 * 1024, "hash_changed_only": True},
    "BALANCED": {"max_files": 4000, "max_hash": 180, "max_bytes": 1024 * 1024, "hash_changed_only": True},
    "HIGH": {"max_files": 8000, "max_hash": 400, "max_bytes": 2 * 1024 * 1024, "hash_changed_only": False},
    "CRITICAL": {"max_files": 12000, "max_hash": 800, "max_bytes": 4 * 1024 * 1024, "hash_changed_only": False},
}


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


def run(cmd: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 1, "", "")


def parse_sshd() -> dict[str, str]:
    path = Path("/etc/ssh/sshd_config")
    values = {
        "PasswordAuthentication": "unknown",
        "PermitRootLogin": "unknown",
        "Port": "22",
        "MaxAuthTries": "unknown",
        "PubkeyAuthentication": "unknown",
    }
    if not path.is_file():
        return values
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[0] in values:
            values[parts[0]] = parts[1]
    return values


def firewall_active() -> bool | None:
    ufw = run(["ufw", "status"], timeout=5)
    if ufw.returncode == 0:
        return "active" in (ufw.stdout or "").lower()
    ipt = run(["iptables", "-S"], timeout=5)
    if ipt.returncode == 0:
        return bool(ipt.stdout.strip())
    return None


def listening_ports() -> list[str]:
    result = run(["ss", "-lntuH"], timeout=5)
    ports: list[str] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            local = parts[4]
            ports.append(local)
    return ports[:80]


def fail2ban_status() -> str:
    result = run(["fail2ban-client", "status"], timeout=5)
    if result.returncode != 0:
        return "not-installed-or-inactive"
    return "active" if "Jail list" in (result.stdout or "") else "inactive"


def failed_logins() -> int | None:
    result = run(["lastb", "-n", "20"], timeout=5)
    if result.returncode != 0:
        return None
    lines = [line for line in (result.stdout or "").splitlines() if line.strip() and not line.startswith("btmp")]
    return len(lines)


def service_active(name: str) -> bool:
    result = run(["systemctl", "is-active", "--quiet", name], timeout=4)
    return result.returncode == 0


def health_services() -> list[dict]:
    names = ["nginx", "mariadb", "mysql", "ssh", "sshd", "fail2ban"]
    # php-fpm unit names vary; probe a short allowlist only.
    for candidate in ("php8.3-fpm", "php8.2-fpm", "php8.1-fpm", "php-fpm"):
        names.append(candidate)
    seen = set()
    rows = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        active = service_active(name)
        if name.startswith("php") and not active:
            continue
        rows.append({"name": name, "active": active})
    return rows


def login_users() -> list[dict]:
    nologin = {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false"}
    rows = []
    for entry in pwd.getpwall():
        if entry.pw_uid < 1000 and entry.pw_uid != 0:
            continue
        if entry.pw_shell in nologin and entry.pw_uid != 0:
            continue
        rows.append({"name": entry.pw_name, "uid": entry.pw_uid, "shell": entry.pw_shell, "home": entry.pw_dir})
    return rows


def sudo_unrestricted() -> bool:
    paths = [Path("/etc/sudoers"), *sorted(Path("/etc/sudoers.d").glob("*"))] if Path("/etc/sudoers.d").is_dir() else [Path("/etc/sudoers")]
    for path in paths:
        if not path.is_file() or path.name.endswith("~"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "NOPASSWD: ALL" in stripped and "NOPASSWD: /usr/local/lib/serverbackup/" not in stripped:
                return True
    return False


def authorized_key_fps() -> list[str]:
    fps: list[str] = []
    ssh_keygen = shutil.which("ssh-keygen")
    homes = ["/root"]
    for entry in pwd.getpwall():
        if entry.pw_uid == 0 or entry.pw_uid >= 1000:
            homes.append(entry.pw_dir)
    for home in homes:
        auth = Path(home) / ".ssh" / "authorized_keys"
        if not auth.is_file() or not ssh_keygen:
            continue
        result = run([ssh_keygen, "-lf", str(auth)], timeout=5)
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                fps.append(parts[1][:32])
    return sorted(set(fps))[:100]


def file_signature(path: Path, header: bytes) -> tuple[str, bool]:
    suffix = path.suffix.lower()
    kind = "unknown"
    if header.startswith(b"\x7fELF"):
        kind = "elf"
    elif header.startswith(b"MZ"):
        kind = "pe"
    elif header.startswith(b"%PDF"):
        kind = "pdf"
    elif header.startswith(b"PK\x03\x04"):
        kind = "zip"
    elif header.startswith(b"\x89PNG"):
        kind = "png"
    elif header[:2] == b"\xff\xd8":
        kind = "jpeg"
    elif header.startswith(b"#!"):
        kind = "script"
    elif b"<?php" in header[:256].lower():
        kind = "php"
    mismatch = False
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt", ".css"} and kind in {"elf", "pe", "script", "php"}:
        mismatch = True
    if suffix in {".php", ".html", ".htm"} and kind in {"elf", "pe"}:
        mismatch = True
    return kind, mismatch


def sha256_limited(path: Path, limit: int) -> str | None:
    digest = hashlib.sha256()
    remaining = limit
    try:
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(1024 * 64, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def walk_scoped(roots: list[str], limits: dict, previous_mtime: float | None) -> tuple[list[dict], int]:
    files: list[dict] = []
    hashed = 0
    max_files = int(limits["max_files"])
    max_hash = int(limits["max_hash"])
    max_bytes = int(limits["max_bytes"])
    hash_changed_only = bool(limits["hash_changed_only"])
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES and not name.startswith(".")]
            for name in filenames:
                if len(files) >= max_files:
                    return files, hashed
                path = Path(dirpath) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    continue
                rec = {
                    "path": str(path),
                    "mode": oct(st.st_mode & 0o777),
                    "uid": st.st_uid,
                    "gid": st.st_gid,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "ino": st.st_ino,
                    "dev": st.st_dev,
                    "type": "file" if stat.S_ISREG(st.st_mode) else "other",
                }
                header = b""
                if stat.S_ISREG(st.st_mode) and st.st_size > 0 and st.st_size <= max_bytes:
                    try:
                        with path.open("rb") as handle:
                            header = handle.read(256)
                    except OSError:
                        header = b""
                if header:
                    sig, mismatch = file_signature(path, header)
                    rec["signature"] = sig
                    rec["mismatch"] = mismatch
                executable = bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                if executable and path.suffix.lower() in {".php", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt"}:
                    rec["executable_new"] = True
                should_hash = False
                if str(path) in CRITICAL_FILES:
                    should_hash = True
                elif hashed < max_hash and stat.S_ISREG(st.st_mode) and st.st_size <= max_bytes:
                    if not hash_changed_only:
                        should_hash = True
                    elif previous_mtime is None or st.st_mtime >= float(previous_mtime):
                        should_hash = path.suffix.lower() in {".conf", ".php", ".sh", ".py", ".env", ".ini", ".json"} or path.parent.name in {"sites-enabled", "sites-available", "sudoers.d"}
                if should_hash and hashed < max_hash:
                    digest = sha256_limited(path, max_bytes)
                    if digest:
                        rec["sha256"] = digest
                        hashed += 1
                files.append(rec)
            if len(files) >= max_files:
                return files, hashed
    return files, hashed


def critical_file_records(limits: dict) -> list[dict]:
    extra = []
    for raw in CRITICAL_FILES:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            st = path.lstat()
        except OSError:
            continue
        rec = {
            "path": str(path),
            "mode": oct(st.st_mode & 0o777),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "ino": st.st_ino,
            "dev": st.st_dev,
            "type": "file",
        }
        digest = sha256_limited(path, int(limits["max_bytes"]))
        if digest:
            rec["sha256"] = digest
        extra.append(rec)
    sudoers_d = Path("/etc/sudoers.d")
    if sudoers_d.is_dir():
        for path in sudoers_d.iterdir():
            if not path.is_file():
                continue
            try:
                st = path.lstat()
            except OSError:
                continue
            extra.append(
                {
                    "path": str(path),
                    "mode": oct(st.st_mode & 0o777),
                    "uid": st.st_uid,
                    "gid": st.st_gid,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "ino": st.st_ino,
                    "dev": st.st_dev,
                    "type": "file",
                    "sha256": sha256_limited(path, int(limits["max_bytes"])),
                }
            )
    return extra


def audit(payload: dict) -> dict:
    mode = str(payload.get("mode") or "BALANCED").upper()
    limits = MODE_LIMITS.get(mode, MODE_LIMITS["BALANCED"])
    roots = [safe_unix(p) for p in payload.get("website_directories") or []]
    ojs = payload.get("ojs_private_files")
    nginx = payload.get("nginx_directory") or "/etc/nginx"
    extra = [safe_unix(p) for p in payload.get("extra_directories") or []]
    if ojs:
        roots.append(safe_unix(str(ojs)))
    roots.append(safe_unix(str(nginx)))
    roots.extend(extra)
    # Config trees only — never / or /home wholesale.
    for optional in ("/etc/ssh", "/etc/php", "/etc/letsencrypt"):
        if os.path.isdir(optional):
            roots.append(optional)
    previous_mtime = payload.get("previous_mtime")
    try:
        previous_mtime = float(previous_mtime) if previous_mtime is not None else None
    except (TypeError, ValueError):
        previous_mtime = None
    files, hashed = walk_scoped(roots, limits, previous_mtime)
    critical = critical_file_records(limits)
    known = {item["path"] for item in files}
    for item in critical:
        if item["path"] not in known:
            files.append(item)
    services = health_services()
    nginx_ok = any(s["name"] == "nginx" and s["active"] for s in services)
    db_ok = any(s["name"] in {"mariadb", "mysql"} and s["active"] for s in services)
    health = {
        "summary": "HEALTHY" if nginx_ok and db_ok else "DEGRADED",
        "services": services,
    }
    layer1 = {
        "sshd": parse_sshd(),
        "firewall_active": firewall_active(),
        "listening_ports": listening_ports(),
        "fail2ban": fail2ban_status(),
        "recent_failed_logins": failed_logins(),
    }
    layer2 = {
        "users": login_users(),
        "sudo_unrestricted": sudo_unrestricted(),
        "authorized_key_fps": authorized_key_fps(),
    }
    return {
        "ok": True,
        "hostname": socket.gethostname(),
        "collected_at_unix": int(time.time()),
        "security_mode": mode,
        "health": health,
        "layer1": layer1,
        "layer2": layer2,
        "integrity": {"examined": len(files), "hashed": hashed, "roots": roots},
        "files": files,
        "enforcement": "none",
    }


def rotate_token(payload: dict) -> dict:
    if str(payload.get("confirmation") or "") != "ROTATE":
        fail("Token rotation requires confirmation=ROTATE")
    token_hash = str(payload.get("token_hash") or "")
    if len(token_hash) != 64 or any(ch not in "0123456789abcdef" for ch in token_hash.lower()):
        fail("token_hash must be a SHA-256 hex digest")
    root = Path("/etc/serverbackup")
    root.mkdir(parents=True, exist_ok=True)
    current = root / "security-token.hash"
    previous = root / "security-token.hash.previous"
    if current.is_file():
        shutil.copy2(current, previous)
    current.write_text(token_hash.lower() + "\n", encoding="utf-8")
    os.chmod(current, 0o600)
    return {"ok": True, "message": "Stored new application token hash. Previous hash retained until verified. SSH keys unchanged."}


def rollback_token(payload: dict) -> dict:
    if str(payload.get("confirmation") or "") != "ROLLBACK":
        fail("Rollback requires confirmation=ROLLBACK")
    root = Path("/etc/serverbackup")
    current = root / "security-token.hash"
    previous = root / "security-token.hash.previous"
    if not previous.is_file():
        return {"ok": True, "message": "No previous application token hash to restore."}
    shutil.copy2(previous, current)
    os.chmod(current, 0o600)
    return {"ok": True, "message": "Restored previous application token hash. Host firewall and sshd were not changed."}


def main() -> None:
    payload = load(sys.argv[1])
    action = str(payload.get("action") or "")
    if action not in ALLOWED:
        fail("action not allowed")
    if action == "security-audit":
        json.dump(audit(payload), sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return
    if action == "security-rotate-token":
        json.dump(rotate_token(payload), sys.stdout)
        sys.stdout.write("\n")
        return
    if action == "security-rollback":
        json.dump(rollback_token(payload), sys.stdout)
        sys.stdout.write("\n")
        return
    fail("unhandled action")


if __name__ == "__main__":
    main()
