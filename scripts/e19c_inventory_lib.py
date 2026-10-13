#!/usr/bin/env python3
"""E1.9C-R2 inventory library: allowlisted, type-validated, secret-safe capture.

Used by scripts/e19c_operator_inventory.sh and adversarial tests.
Never prints environment values, connection strings, tokens, or private keys.
Every externally sourced field is format-validated before disk write.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REQUIRED_SERVICES = ("backend", "frontend", "proxy")
# Accept common proxy service names mapped to logical "proxy"
PROXY_SERVICE_ALIASES = frozenset({"proxy", "nginx", "caddy", "traefik", "edge", "web"})
APP_SERVICE_ALIASES = {
    "backend": frozenset({"backend", "api", "app"}),
    "frontend": frozenset({"frontend", "ui", "webapp"}),
    "proxy": PROXY_SERVICE_ALIASES,
}

# Exact files permitted in a shareable archive (basename only).
APPROVED_ARCHIVE_FILES = frozenset(
    {
        "00_return_summary.txt",
        "01_identity.txt",
        "02_project_services.json",
        "04_git.txt",
        "05_fingerprints.txt",
        "06_images.txt",
        "07_rollback.txt",
        "08_compose_services.txt",
        "09_compose_structure.json",
        "10_volumes_mounts.txt",
        "11_health.txt",
        "12_env_names.txt",
        "13_runner.txt",
        "14_baseline_and_config.txt",
        "15_manifest.txt",
    }
)

SENSITIVE_KEY = re.compile(
    r"(PASSWORD|SECRET|TOKEN|PRIVATE|API[_-]?KEY|AUTH|CREDENTIAL|DATABASE_URL|"
    r"POSTGRES|REDIS_URL|CONNECTION_STRING|ADMIN_PASS|JWT|SESSION|SMTP|"
    r"AWS_|GCP_|GOOGLE_|PRIVATE_KEY|PUBLISHER.*KEY|BEGIN\s)",
    re.I,
)
# DB/broker URIs only — do not treat http(s) health URLs as secrets.
CONN_URI = re.compile(r"(?i)\b(postgres|postgresql|redis|mysql|mongodb|amqp)://\S+")
SECRETISH = re.compile(r"(?i)(password|secret|token|private[_-]?key|bearer\s+[a-z0-9\.\-_]+)")
CREDENTIAL_LIKE = re.compile(
    r"(?i)(://|[?&](password|token|secret|key|auth)=|:\S{4,}@|"
    r"\b(AKIA|ghp_|gho_|github_pat_|xox[baprs]-|eyJ[A-Za-z0-9_-]{10,}\.))|"
    r"(password|secret|token|api[_-]?key)\s*[:=]"
)
# Keys that may contain the word "secret" but are inventory metadata, not credentials.
META_KEYS_ALLOW = frozenset(
    {
        "secret_hits",
        "secret_scanner",
        "share_safe",
        "scanner_hits",
        "archive_allowed",
    }
)

RE_HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
RE_DOCKER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RE_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RE_GIT_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
RE_GIT_SHA = re.compile(r"^[0-9a-f]{7,40}$")
RE_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
RE_DIGEST_REF = re.compile(r"^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")
RE_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,250}$")
RE_MOUNT_DEST = re.compile(r"^/[A-Za-z0-9._/-]{0,250}$")
RE_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
RE_HTTP = re.compile(r"^(?:[1-5][0-9]{2}|ERR|UNKNOWN)$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RE_RUNNER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RE_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

HEALTH_STATUS_ALLOW = frozenset({"healthy", "unhealthy", "degraded", "ok", "up", "down", "UNKNOWN"})
HEALTH_DB_ALLOW = frozenset({"postgresql", "postgres", "sqlite", "mysql", "unknown", "UNKNOWN"})
HEALTH_ENV_ALLOW = frozenset({"production", "development", "staging", "test", "UNKNOWN"})
RUNNER_STATUS_ALLOW = frozenset({"online", "offline", "idle", "active", "busy", "UNKNOWN"})
DOCKER_STATUS_ALLOW_PREFIX = ("Up", "Exited", "Created", "Restarting", "Paused", "Dead", "Removing")
MOUNT_TYPES = frozenset({"volume", "bind", "tmpfs", "npipe", "UNKNOWN"})
YN_ALLOW = frozenset({"yes", "no", "UNKNOWN", "object_missing", "missing_locally"})
IDENTITY_ALLOW = frozenset({"PASS", "STOP", "FAIL", "UNKNOWN"})
PERM_ALLOW = frozenset(
    {"ok", "denied", "unauthorized", "not_found", "error", "gh_missing", "skipped", "UNKNOWN"}
)


class InventoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code  # STOP | FAIL | UNKNOWN
        super().__init__(message)


@dataclass
class InventoryResult:
    status: str  # OK | STOP | FAIL
    files: dict[str, str] = field(default_factory=dict)
    summary: dict[str, str] = field(default_factory=dict)
    share_safe: bool = False
    stop_reason: str | None = None
    archive_path: str | None = None


def _has_credential_like(value: str) -> bool:
    if not value:
        return False
    if CREDENTIAL_LIKE.search(value):
        return True
    if CONN_URI.search(value):
        return True
    if " " in value and SECRETISH.search(value):
        return True
    return False


def validate_or_unknown(
    value: Any,
    *,
    kind: str,
    max_len: int,
    pattern: re.Pattern[str] | None = None,
    allow: frozenset[str] | None = None,
    allow_prefix: tuple[str, ...] | None = None,
) -> str:
    """Constrain an externally sourced value. Malformed → UNKNOWN (never raw unsafe literal)."""
    if value is None:
        return "UNKNOWN"
    if not isinstance(value, (str, int, float, bool)):
        return "UNKNOWN"
    text = str(value).strip()
    if not text:
        return "UNKNOWN"
    if len(text) > max_len:
        return "UNKNOWN"
    if any(ch in text for ch in ("\n", "\r", "\t", "\x00")):
        return "UNKNOWN"
    if _has_credential_like(text):
        return "UNKNOWN"
    if allow is not None:
        return text if text in allow else "UNKNOWN"
    if allow_prefix is not None:
        if any(text == p or text.startswith(p + " ") or text.startswith(p + "(") for p in allow_prefix):
            # collapse docker status to prefix token only
            for p in allow_prefix:
                if text == p or text.startswith(p + " ") or text.startswith(p + "("):
                    return p
        return "UNKNOWN"
    if pattern is not None and not pattern.fullmatch(text):
        return "UNKNOWN"
    # image refs must not embed user:password@
    if kind == "image_ref" and re.search(r":[^/]+@", text):
        return "UNKNOWN"
    return text


def v_hostname(v: Any) -> str:
    return validate_or_unknown(v, kind="hostname", max_len=253, pattern=RE_HOSTNAME)


def v_docker_name(v: Any) -> str:
    return validate_or_unknown(v, kind="docker_name", max_len=128, pattern=RE_DOCKER_NAME)


def v_service(v: Any) -> str:
    return validate_or_unknown(v, kind="service", max_len=64, pattern=RE_SERVICE)


def v_git_branch(v: Any) -> str:
    out = validate_or_unknown(v, kind="git_branch", max_len=200, pattern=RE_GIT_BRANCH)
    if out != "UNKNOWN" and (".." in out or out.startswith("/") or out.endswith("/")):
        return "UNKNOWN"
    return out


def v_git_sha(v: Any) -> str:
    return validate_or_unknown(v, kind="git_sha", max_len=40, pattern=RE_GIT_SHA)


def v_image_id(v: Any) -> str:
    return validate_or_unknown(v, kind="image_id", max_len=80, pattern=RE_IMAGE_ID)


def v_image_ref(v: Any) -> str:
    return validate_or_unknown(v, kind="image_ref", max_len=250, pattern=RE_IMAGE_REF)


def v_mount_dest(v: Any) -> str:
    out = validate_or_unknown(v, kind="mount_dest", max_len=250, pattern=RE_MOUNT_DEST)
    if out != "UNKNOWN" and (".." in out or "//" in out):
        return "UNKNOWN"
    return out


def v_env_name(v: Any) -> str:
    return validate_or_unknown(v, kind="env_name", max_len=128, pattern=RE_ENV_NAME)


def v_http_code(v: Any) -> str:
    return validate_or_unknown(v, kind="http", max_len=7, pattern=RE_HTTP)


def v_sha256(v: Any) -> str:
    return validate_or_unknown(v, kind="sha256", max_len=64, pattern=RE_SHA256)


def v_runner_name(v: Any) -> str:
    return validate_or_unknown(v, kind="runner_name", max_len=64, pattern=RE_RUNNER_NAME)


def v_runner_status(v: Any) -> str:
    return validate_or_unknown(v, kind="runner_status", max_len=16, allow=RUNNER_STATUS_ALLOW)


def v_docker_status(v: Any) -> str:
    return validate_or_unknown(
        v, kind="docker_status", max_len=64, allow_prefix=DOCKER_STATUS_ALLOW_PREFIX
    )


def v_mount_type(v: Any) -> str:
    return validate_or_unknown(v, kind="mount_type", max_len=16, allow=MOUNT_TYPES)


def v_health_status(v: Any) -> str:
    text = str(v).strip().lower() if v is not None else ""
    return validate_or_unknown(text, kind="health_status", max_len=32, allow=HEALTH_STATUS_ALLOW)


def v_health_db(v: Any) -> str:
    text = str(v).strip().lower() if v is not None else ""
    return validate_or_unknown(text, kind="health_db", max_len=32, allow=HEALTH_DB_ALLOW)


def v_health_env(v: Any) -> str:
    text = str(v).strip().lower() if v is not None else ""
    return validate_or_unknown(text, kind="health_env", max_len=32, allow=HEALTH_ENV_ALLOW)


def v_health_version(v: Any) -> str:
    return validate_or_unknown(
        v, kind="health_version", max_len=32, pattern=re.compile(r"^[A-Za-z0-9._+-]{1,32}$")
    )


def v_enum(v: Any, allow: frozenset[str]) -> str:
    return validate_or_unknown(v, kind="enum", max_len=64, allow=allow)


def v_repo_digests(raw: Any) -> str:
    """Validate RepoDigests JSON list; return compact JSON or UNKNOWN."""
    try:
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
    except Exception:
        return "UNKNOWN"
    if not isinstance(data, list):
        return "UNKNOWN"
    cleaned = []
    for item in data[:16]:
        if not isinstance(item, str):
            return "UNKNOWN"
        one = validate_or_unknown(item, kind="digest_ref", max_len=300, pattern=RE_DIGEST_REF)
        if one == "UNKNOWN":
            return "UNKNOWN"
        cleaned.append(one)
    return json.dumps(cleaned, separators=(",", ":"))


def v_repo_tags(raw: Any) -> str:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return "UNKNOWN"
    if not isinstance(data, list):
        return "UNKNOWN"
    cleaned = []
    for item in data[:16]:
        tag = v_image_ref(item)
        if tag == "UNKNOWN":
            return "UNKNOWN"
        cleaned.append(tag)
    return json.dumps(cleaned, separators=(",", ":"))


def harden_file_mode(path: Path, mode: int = 0o600) -> None:
    os.chmod(path, mode)


def build_allowlisted_archive(out_path: Path, files: dict[str, str]) -> tuple[str | None, str]:
    """Create archive with precisely approved files. Returns (archive_path|None, result)."""
    # Drop any unexpected files from the directory before archiving
    for child in list(out_path.iterdir()):
        if child.name not in APPROVED_ARCHIVE_FILES and child.name not in {
            "STOP.txt",
            "STOP_SECRETS.txt",
        }:
            try:
                child.unlink()
            except OSError:
                return None, "FAIL"
            files.pop(child.name, None)

    approved_present = sorted(n for n in files if n in APPROVED_ARCHIVE_FILES)
    # Summary + manifest must exist before archive
    if "00_return_summary.txt" not in files or "15_manifest.txt" not in files:
        return None, "FAIL"

    archive_path = out_path.parent / f"{out_path.name}.tar.gz"
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for name in approved_present:
                fp = out_path / name
                if not fp.is_file():
                    return None, "FAIL"
                harden_file_mode(fp, 0o600)
                tar.add(fp, arcname=f"{out_path.name}/{name}")
        harden_file_mode(archive_path, 0o600)
        # Verify members
        with tarfile.open(archive_path, "r:gz") as tar:
            members = sorted(
                m.name.split("/", 1)[-1]
                for m in tar.getmembers()
                if m.isfile()
            )
        expected = approved_present
        if members != expected:
            try:
                archive_path.unlink()
            except OSError:
                pass
            return None, "FAIL"
    except Exception:
        return None, "FAIL"
    return str(archive_path), "OK"


def _run(
    argv: list[str],
    *,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "command_not_found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def resolve_out_dir(out_dir: str, app_dir: str) -> Path:
    """Resolve symlinks and restrict OUT_DIR to a private path outside APP_DIR."""
    if not out_dir:
        raise InventoryError("STOP", "OUT_DIR is required")
    raw = Path(out_dir)
    if not raw.is_absolute():
        raise InventoryError("STOP", "OUT_DIR must be absolute")

    app_resolved = Path(app_dir).resolve()
    # Resolve existing components; create leaf later with mode 0700
    parent = raw.parent
    try:
        parent_resolved = parent.resolve(strict=False)
    except Exception as exc:  # pragma: no cover
        raise InventoryError("STOP", f"OUT_DIR parent unresolvable: {exc}") from exc

    candidate = (parent_resolved / raw.name).resolve(strict=False)

    try:
        candidate.relative_to(app_resolved)
        raise InventoryError("STOP", "OUT_DIR must not be inside APP_DIR")
    except ValueError:
        pass
    # Also block if APP_DIR is inside a symlink trick pointing into app
    if str(candidate).startswith(str(app_resolved) + os.sep) or candidate == app_resolved:
        raise InventoryError("STOP", "OUT_DIR resolves inside APP_DIR")

    # Disallow world-writable sticky locations that are not the operator's explicit path
    # Operator-controlled: must be under /tmp, /var/tmp, or $HOME
    home = Path(os.path.expanduser("~")).resolve()
    allowed_roots = [Path("/tmp").resolve(), Path("/var/tmp").resolve(), home]
    if not any(
        candidate == root or str(candidate).startswith(str(root) + os.sep) for root in allowed_roots
    ):
        raise InventoryError(
            "STOP",
            "OUT_DIR must resolve under /tmp, /var/tmp, or $HOME (operator-controlled)",
        )

    candidate.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Ensure directory mode is private
    os.chmod(candidate, 0o700)
    st = candidate.stat()
    if st.st_uid != os.getuid():
        raise InventoryError("STOP", "OUT_DIR is not owned by current user")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        # try fix once
        os.chmod(candidate, 0o700)
        st = candidate.stat()
        if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise InventoryError("STOP", "OUT_DIR must be mode 0700 (private)")
    return candidate


def parse_compose_structure(compose_text: str) -> dict[str, Any]:
    """Allowlisted structural inventory from compose file text (not `compose config`)."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise InventoryError("FAIL", "PyYAML required to parse compose file") from exc

    data = yaml.safe_load(compose_text) or {}
    if not isinstance(data, dict):
        raise InventoryError("FAIL", "compose root must be a mapping")

    services_out: dict[str, Any] = {}
    services = data.get("services") or {}
    if not isinstance(services, dict):
        raise InventoryError("FAIL", "compose.services must be a mapping")

    for name, svc in services.items():
        if not isinstance(svc, dict):
            services_out[str(name)] = {"parse": "UNKNOWN"}
            continue
        env_names: list[str] = []
        env = svc.get("environment")
        if isinstance(env, dict):
            env_names = sorted(str(k) for k in env.keys())
        elif isinstance(env, list):
            for item in env:
                if isinstance(item, str) and "=" in item:
                    env_names.append(item.split("=", 1)[0])
                elif isinstance(item, str):
                    env_names.append(item)
                elif isinstance(item, dict):
                    env_names.extend(str(k) for k in item.keys())
            env_names = sorted(set(env_names))

        mounts: list[dict[str, str]] = []
        for vol in svc.get("volumes") or []:
            if isinstance(vol, str):
                # src:dst[:mode] — record destination only + whether named/bind by heuristic
                parts = vol.split(":")
                if len(parts) >= 2:
                    src, dst = parts[0], parts[1]
                    kind = "named" if "/" not in src and not src.startswith(".") else "bind_or_path"
                    mounts.append({"destination": dst, "source_kind": kind, "source_name": src if kind == "named" else "<path>"})
                else:
                    mounts.append({"destination": "UNKNOWN", "source_kind": "UNKNOWN", "source_name": "UNKNOWN"})
            elif isinstance(vol, dict):
                mounts.append(
                    {
                        "destination": str(vol.get("target") or vol.get("destination") or "UNKNOWN"),
                        "source_kind": str(vol.get("type") or "UNKNOWN"),
                        "source_name": str(vol.get("source") or vol.get("name") or "UNKNOWN")
                        if vol.get("type") == "volume"
                        else "<path>",
                    }
                )

        ports = []
        for p in svc.get("ports") or []:
            ports.append(str(p) if not isinstance(p, dict) else str(p.get("published", "UNKNOWN")))

        services_out[str(name)] = {
            "image_ref_present": bool(svc.get("image") or svc.get("build")),
            "env_names": env_names,
            "mounts": mounts,
            "ports_published": ports,
            "networks": sorted(str(n) for n in (svc.get("networks") or {}) )
            if isinstance(svc.get("networks"), dict)
            else [str(n) for n in (svc.get("networks") or [])],
            "depends_on": sorted(str(x) for x in (svc.get("depends_on") or {}))
            if isinstance(svc.get("depends_on"), dict)
            else [str(x) for x in (svc.get("depends_on") or [])],
        }

    volumes_top = data.get("volumes") or {}
    networks_top = data.get("networks") or {}
    return {
        "service_names": sorted(services_out.keys()),
        "services": services_out,
        "named_volumes": sorted(str(k) for k in volumes_top.keys()) if isinstance(volumes_top, dict) else [],
        "networks": sorted(str(k) for k in networks_top.keys()) if isinstance(networks_top, dict) else [],
    }


def parse_docker_ps_lines(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name = v_docker_name(parts[0])
        project = v_docker_name(parts[1])
        service = v_service(parts[2])
        status = v_docker_status(parts[3])
        image = v_image_ref(parts[4])
        # Drop rows whose critical identity fields failed validation
        if name == "UNKNOWN" or project == "UNKNOWN" or service == "UNKNOWN":
            continue
        rows.append(
            {
                "name": name,
                "project": project,
                "service": service,
                "status": status,
                "image": image,
            }
        )
    return rows


def verify_project_services(
    rows: list[dict[str, str]],
    expected_project: str,
) -> dict[str, Any]:
    """Require backend, frontend, proxy containers labeled with expected_project."""
    expected_project = v_docker_name(expected_project)
    in_project = [r for r in rows if r.get("project") == expected_project]
    other_projects = sorted(
        {
            r["project"]
            for r in rows
            if r.get("project") and r["project"] != expected_project and r["project"] != "UNKNOWN"
        }
    )

    found: dict[str, dict[str, str]] = {}
    for logical, aliases in APP_SERVICE_ALIASES.items():
        matches = [r for r in in_project if r.get("service") in aliases]
        if matches:
            found[logical] = matches[0]
        else:
            found[logical] = {}

    missing = [s for s in REQUIRED_SERVICES if not found[s]]
    result = {
        "expected_project": expected_project if expected_project != "UNKNOWN" else "FAIL",
        "containers_in_project": [
            {
                "name": r["name"],
                "service": r["service"],
                "status": r["status"],
                "image": r["image"],
            }
            for r in in_project
        ],
        "other_projects_present": other_projects,
        "required": {},
        "missing_required": missing,
    }
    for logical in REQUIRED_SERVICES:
        row = found[logical]
        if row:
            result["required"][logical] = {
                "result": "PASS",
                "container": row["name"],
                "service_label": row["service"],
                "status": row["status"],
                "image": row["image"],
            }
        else:
            result["required"][logical] = {
                "result": "FAIL",
                "container": "UNKNOWN",
                "service_label": "UNKNOWN",
                "status": "UNKNOWN",
                "image": "UNKNOWN",
            }
    return result


def allowlisted_health_fields(body: str) -> dict[str, Any]:
    """Parse health JSON in-memory; keep only allowlisted, type-validated keys."""
    try:
        data = json.loads(body)
    except Exception:
        return {"parse": "FAIL", "status": "UNKNOWN"}
    if not isinstance(data, dict):
        return {"parse": "FAIL", "status": "UNKNOWN"}
    out: dict[str, Any] = {"parse": "OK"}
    if "status" in data:
        out["status"] = v_health_status(data.get("status"))
    if "version" in data:
        out["version"] = v_health_version(data.get("version"))
    if "environment" in data:
        out["environment"] = v_health_env(data.get("environment"))
    if "database" in data:
        out["database"] = v_health_db(data.get("database"))
    return out


def scrub_gh_error(stderr: str, returncode: int) -> dict[str, str]:
    """Map gh failures to allowlisted permission/HTTP results — no raw error bodies."""
    low = (stderr or "").lower()
    http = "UNKNOWN"
    m = re.search(r"\((?:HTTP\s*)?(\d{3})\)", stderr or "")
    if m:
        http = m.group(1)
    if "403" in low or "resource not accessible" in low or "forbidden" in low:
        return {"result": "FAIL", "permission": "denied", "http": http if http != "UNKNOWN" else "403"}
    if "401" in low or "unauthorized" in low:
        return {"result": "FAIL", "permission": "unauthorized", "http": http if http != "UNKNOWN" else "401"}
    if "404" in low or "not found" in low:
        return {"result": "FAIL", "permission": "not_found", "http": http if http != "UNKNOWN" else "404"}
    if returncode == 127 or "command_not_found" in low:
        return {"result": "FAIL", "permission": "gh_missing", "http": "UNKNOWN"}
    if returncode != 0:
        return {"result": "FAIL", "permission": "error", "http": http}
    return {"result": "OK", "permission": "ok", "http": "200"}


def scan_for_secrets(text: str) -> list[str]:
    hits = []
    if "BEGIN " in text and "PRIVATE KEY" in text:
        hits.append("private_key_block")
    if CONN_URI.search(text):
        for m in CONN_URI.finditer(text):
            if "<redacted>" not in m.group(0).lower() and "://<redacted>" not in m.group(0).lower():
                hits.append("connection_uri")
                break
    allow_vals = {
        "<redacted>",
        "UNKNOWN",
        "1",
        "0",
        "yes",
        "no",
        "PASS",
        "FAIL",
        "STOP",
        "OK",
        "missing_locally",
        "object_missing",
        "none",
        "skipped",
    }
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key_s = key.strip()
        val_s = val.strip()
        if key_s in META_KEYS_ALLOW:
            continue
        if SENSITIVE_KEY.search(key_s):
            if val_s and val_s not in allow_vals and not val_s.startswith("("):
                if SECRETISH.search(line) or len(val_s) > 12:
                    hits.append(f"sensitive_assignment:{key_s[:40]}")
    # password/secret/token assignments with non-redacted values
    for m in re.finditer(
        r"(?i)\b(password|secret|token)\b\s*[:=]\s*['\"]?([^'\"<\s,{}\[\]]{4,})",
        text,
    ):
        key_word, val = m.group(1), m.group(2)
        if val.lower() in {v.lower() for v in allow_vals}:
            continue
        # Ignore JSON keys like "POSTGRES_PASSWORD" without values (value would be next token)
        if val.endswith(",") or val in {"true", "false", "null"}:
            continue
        hits.append("password_like_assignment")
        break
    return sorted(set(hits))


def filter_runner_json(payload: str) -> dict[str, Any]:
    """Keep allowlisted runner fields only; type-validate each field."""
    try:
        data = json.loads(payload)
    except Exception:
        return {"result": "FAIL", "parse": "FAIL"}
    runners = data if isinstance(data, list) else data.get("runners") if isinstance(data, dict) else None
    if runners is None and isinstance(data, dict) and "name" in data:
        runners = [data]
    if not isinstance(runners, list):
        return {"result": "FAIL", "parse": "FAIL"}
    out = []
    label_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    for r in runners[:32]:
        if not isinstance(r, dict):
            continue
        labels = []
        for lab in (r.get("labels") or [])[:32]:
            raw = lab.get("name") if isinstance(lab, dict) else lab if isinstance(lab, str) else None
            lab_v = validate_or_unknown(raw, kind="label", max_len=64, pattern=label_re)
            if lab_v != "UNKNOWN":
                labels.append(lab_v)
        rid = r.get("id", "UNKNOWN")
        if isinstance(rid, bool) or not isinstance(rid, (int, str)):
            rid = "UNKNOWN"
        elif isinstance(rid, str) and not re.fullmatch(r"[0-9]{1,12}", rid):
            rid = "UNKNOWN"
        elif isinstance(rid, int) and not (0 <= rid < 10**12):
            rid = "UNKNOWN"
        busy = r.get("busy", "UNKNOWN")
        if not isinstance(busy, bool):
            busy = "UNKNOWN"
        out.append(
            {
                "name": v_runner_name(r.get("name")),
                "id": rid,
                "status": v_runner_status(r.get("status")),
                "busy": busy,
                "labels": labels,
            }
        )
    return {"result": "OK", "runners": out}


def filter_actions_runs(payload: str, expected_sha: str) -> dict[str, Any]:
    try:
        data = json.loads(payload)
    except Exception:
        return {"result": "FAIL", "parse": "FAIL"}
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    if runs is None and isinstance(data, dict) and "runs" in data:
        runs = data["runs"]
    if not isinstance(runs, list):
        return {"result": "FAIL", "parse": "FAIL"}
    expected_sha = v_git_sha(expected_sha)
    keep = []
    name_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}$")
    path_re = re.compile(r"^[A-Za-z0-9._-]{1,80}\.yml$")
    status_allow = frozenset({"completed", "in_progress", "queued", "waiting", "requested", "pending", "UNKNOWN"})
    concl_allow = frozenset(
        {
            "success",
            "failure",
            "cancelled",
            "skipped",
            "timed_out",
            "action_required",
            "neutral",
            "stale",
            "UNKNOWN",
            "None",
        }
    )
    event_allow = frozenset({"push", "pull_request", "workflow_dispatch", "schedule", "UNKNOWN"})
    for r in runs[:50]:
        if not isinstance(r, dict):
            continue
        head = v_git_sha(r.get("head_sha") or "")
        if expected_sha != "UNKNOWN" and head != "UNKNOWN" and head != expected_sha:
            continue
        path = str(r.get("path") or "").replace("\\", "/").split("/")[-1]
        path_v = validate_or_unknown(path, kind="wf_path", max_len=80, pattern=path_re)
        name_v = validate_or_unknown(r.get("name"), kind="wf_name", max_len=80, pattern=name_re)
        keep.append(
            {
                "name": name_v,
                "path": path_v,
                "head_sha": head if head != "UNKNOWN" else "UNKNOWN",
                "status": v_enum(r.get("status") or "UNKNOWN", status_allow),
                "conclusion": v_enum(str(r.get("conclusion") if r.get("conclusion") is not None else "UNKNOWN"), concl_allow),
                "event": v_enum(r.get("event") or "UNKNOWN", event_allow),
            }
        )
    return {"result": "OK", "count": len(keep), "runs": keep}


CmdFn = Callable[[list[str]], tuple[int, str, str]]


def default_cmd(argv: list[str]) -> tuple[int, str, str]:
    return _run(argv)


def run_inventory(
    *,
    app_dir: str,
    out_dir: str,
    expected_host: str = "zhzh",
    expected_project: str = "sateye-fz2ic4",
    expected_baseline: str = "1e71b7abaa0fa8d4b70225d949afc8ae79923bb6",
    approved_tip: str = "e3012ce0a26e049d0af981d5994d0d829c3b647e",
    include_runner_checks: bool = True,
    hostname_value: str | None = None,
    cmd: CmdFn | None = None,
    compose_file_name: str = "docker-compose.yml",
    health_urls: list[str] | None = None,
) -> InventoryResult:
    """Execute read-only inventory. Identity failure returns STOP with no further inspection files."""
    run = cmd or default_cmd
    files: dict[str, str] = {}
    summary: dict[str, str] = {
        "hostname": "UNKNOWN",
        "compose_project": "UNKNOWN",
        "app_dir": app_dir,
        "live_branch": "UNKNOWN",
        "live_commit": "UNKNOWN",
        "baseline_1e71b7a_ancestor": "UNKNOWN",
        "backend_image_id": "UNKNOWN",
        "backend_repo_digest": "UNKNOWN",
        "frontend_image_id": "UNKNOWN",
        "frontend_repo_digest": "UNKNOWN",
        "proxy_image_id": "UNKNOWN",
        "env_sha256": "UNKNOWN",
        "compose_sha256": "UNKNOWN",
        "runner_status": "UNKNOWN",
        "actions_runs_api": "UNKNOWN",
        "tools_runtime_http": "UNKNOWN",
        "composites_http": "UNKNOWN",
        "ev_pack_env_names_present": "UNKNOWN",
        "identity_result": "UNKNOWN",
        "share_safe": "no",
        "changes_made": "none",
    }

    # OUT_DIR validation first (no app inspection yet beyond path checks)
    try:
        out_path = resolve_out_dir(out_dir, app_dir)
    except InventoryError as exc:
        return InventoryResult(status=exc.code, stop_reason=str(exc), share_safe=False, summary=summary)

    def write(name: str, content: str) -> None:
        # Only approved evidence filenames (plus STOP markers) may be written
        if name not in APPROVED_ARCHIVE_FILES and name not in {"STOP.txt", "STOP_SECRETS.txt"}:
            raise InventoryError("FAIL", f"unapproved output file: {name}")
        files[name] = content
        target = out_path / name
        target.write_text(content, encoding="utf-8")
        harden_file_mode(target, 0o600)

    raw_host = hostname_value if hostname_value is not None else (run(["hostname"])[1].strip() or "")
    host = v_hostname(raw_host)
    expected_host_v = v_hostname(expected_host)
    expected_project_v = v_docker_name(expected_project)
    approved_tip_v = v_git_sha(approved_tip)
    expected_baseline_v = v_git_sha(expected_baseline)
    summary["hostname"] = host
    identity_lines = [
        f"captured_at=UNKNOWN",  # filled below
        f"hostname={summary['hostname']}",
        f"app_dir={app_dir}",
        f"app_dir_exists={'1' if Path(app_dir).is_dir() else '0'}",
        f"expected_host={expected_host_v}",
        f"expected_project={expected_project_v}",
        f"approved_tip={approved_tip_v}",
        f"expected_baseline={expected_baseline_v}",
    ]
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity_lines[0] = f"captured_at={ts if RE_ISO_TS.fullmatch(ts) else 'UNKNOWN'}"

    # --- HARD IDENTITY GATE (must pass before any further inventory) ---
    if host == "UNKNOWN" or expected_host_v == "UNKNOWN" or host != expected_host_v:
        reason = (
            "STOP: hostname validation/identity failed "
            f"(got={summary['hostname']} expected={expected_host_v})"
        )
        identity_lines.append("identity_result=STOP")
        identity_lines.append("stop_reason=hostname_mismatch_or_invalid")
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    if not Path(app_dir).is_dir():
        reason = "STOP: APP_DIR missing"
        identity_lines.append("identity_result=STOP")
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    if expected_project_v == "UNKNOWN":
        reason = "STOP: expected compose project invalid"
        identity_lines.append("identity_result=STOP")
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    # Container identity for required services in expected project only
    rc, ps_out, ps_err = run(
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}\t{{.Label \"com.docker.compose.service\"}}\t{{.Status}}\t{{.Image}}",
        ]
    )
    if rc != 0:
        reason = "STOP: docker ps failed — cannot verify project services"
        identity_lines.append("identity_result=STOP")
        identity_lines.append("docker_ps=FAIL")
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    rows = parse_docker_ps_lines(ps_out)
    svc_check = verify_project_services(rows, expected_project_v)
    write("02_project_services.json", json.dumps(svc_check, indent=2, sort_keys=True) + "\n")

    if svc_check["missing_required"]:
        reason = (
            "STOP: required services missing from project "
            f"{expected_project_v}: {','.join(svc_check['missing_required'])}"
        )
        identity_lines.append("identity_result=STOP")
        identity_lines.append(f"missing_required={','.join(svc_check['missing_required'])}")
        if svc_check["other_projects_present"]:
            identity_lines.append(
                "other_projects_ignored="
                + ",".join(v_docker_name(p) for p in svc_check["other_projects_present"])
            )
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        summary["compose_project"] = expected_project_v
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    identity_lines.append("identity_result=PASS")
    identity_lines.append(f"compose_project={expected_project_v}")
    for logical in REQUIRED_SERVICES:
        info = svc_check["required"][logical]
        identity_lines.append(
            f"{logical}_container={info['container']}|service={info['service_label']}|status={info['status']}"
        )
    write("01_identity.txt", "\n".join(identity_lines) + "\n")
    summary["identity_result"] = "PASS"
    summary["compose_project"] = expected_project_v

    verified_containers = {
        logical: svc_check["required"][logical]["container"] for logical in REQUIRED_SERVICES
    }

    # --- Git (read-only) ---
    git: dict[str, str] = {}
    app = Path(app_dir)
    if (app / ".git").exists():
        def git_out(args: list[str]) -> str:
            r, o, e = run(["git", "-C", app_dir, *args])
            return o.strip() if r == 0 else ""

        branch = v_git_branch(git_out(["branch", "--show-current"]) or "")
        commit = v_git_sha(git_out(["rev-parse", "HEAD"]) or "")
        short = v_git_sha(git_out(["rev-parse", "--short", "HEAD"]) or "")
        # status summary is not shared as free text — collapse to dirty flag only
        status_raw = git_out(["status", "--porcelain"])
        dirty = "yes" if status_raw.strip() else "no"
        baseline_ancestor = "UNKNOWN"
        if expected_baseline_v == "UNKNOWN":
            baseline_ancestor = "UNKNOWN"
        else:
            r, o, e = run(["git", "-C", app_dir, "cat-file", "-e", f"{expected_baseline_v}^{{commit}}"])
            if r == 0:
                r2, _, _ = run(
                    ["git", "-C", app_dir, "merge-base", "--is-ancestor", expected_baseline_v, "HEAD"]
                )
                baseline_ancestor = "yes" if r2 == 0 else "no"
            else:
                baseline_ancestor = "object_missing"
        tip_eq = (
            "yes"
            if commit != "UNKNOWN" and approved_tip_v != "UNKNOWN" and commit == approved_tip_v
            else ("no" if commit != "UNKNOWN" else "UNKNOWN")
        )
        git = {
            "branch": branch,
            "commit": commit,
            "commit_short": short,
            "working_tree_dirty": dirty,
            "baseline_1e71b7a_ancestor": v_enum(baseline_ancestor, YN_ALLOW),
            "live_equals_approved_tip_e3012ce": v_enum(tip_eq, frozenset({"yes", "no", "UNKNOWN"})),
        }
    else:
        git = {
            "branch": "UNKNOWN",
            "commit": "UNKNOWN",
            "commit_short": "UNKNOWN",
            "working_tree_dirty": "UNKNOWN",
            "baseline_1e71b7a_ancestor": "UNKNOWN",
            "live_equals_approved_tip_e3012ce": "UNKNOWN",
            "git": "MISSING",
        }
    write("04_git.txt", "\n".join(f"{k}={v}" for k, v in git.items()) + "\n")
    summary["live_branch"] = git.get("branch", "UNKNOWN")
    summary["live_commit"] = git.get("commit", "UNKNOWN")
    summary["baseline_1e71b7a_ancestor"] = git.get("baseline_1e71b7a_ancestor", "UNKNOWN")

    # Fingerprints — never read .env contents into output
    fp = []
    env_path = app / ".env"
    if env_path.is_file():
        fp.append("env_present=1")
        size = env_path.stat().st_size
        fp.append(f"env_size={size if isinstance(size, int) and 0 <= size < 10**9 else 'UNKNOWN'}")
        r, o, e = run(["sha256sum", str(env_path)])
        digest = v_sha256(o.split()[0] if r == 0 and o else "")
        fp.append(f"env_sha256={digest}")
        summary["env_sha256"] = digest
    else:
        fp.append("env_present=0")
        fp.append("env_sha256=UNKNOWN")
    compose_path = app / compose_file_name
    if compose_path.is_file():
        r, o, e = run(["sha256sum", str(compose_path)])
        digest = v_sha256(o.split()[0] if r == 0 and o else "")
        fp.append(f"compose_sha256={digest}")
        summary["compose_sha256"] = digest
        try:
            structure = parse_compose_structure(compose_path.read_text(encoding="utf-8", errors="replace"))
            # Re-validate service/env/mount names in structure
            structure["service_names"] = [
                n for n in (v_service(s) for s in structure["service_names"]) if n != "UNKNOWN"
            ]
            for sname, svc in list(structure["services"].items()):
                vs = v_service(sname)
                if vs == "UNKNOWN":
                    structure["services"].pop(sname, None)
                    continue
                if sname != vs:
                    structure["services"][vs] = structure["services"].pop(sname)
                    sname = vs
                svc["env_names"] = [n for n in (v_env_name(x) for x in svc.get("env_names") or []) if n != "UNKNOWN"]
                mounts = []
                for m in svc.get("mounts") or []:
                    mounts.append(
                        {
                            "destination": v_mount_dest(m.get("destination")),
                            "source_kind": v_enum(
                                m.get("source_kind"),
                                frozenset({"named", "bind_or_path", "volume", "bind", "UNKNOWN"}),
                            ),
                            "source_name": v_docker_name(m.get("source_name"))
                            if m.get("source_kind") in {"named", "volume"}
                            else "<path>",
                        }
                    )
                svc["mounts"] = mounts
            structure["named_volumes"] = [
                n for n in (v_docker_name(x) for x in structure.get("named_volumes") or []) if n != "UNKNOWN"
            ]
            write("09_compose_structure.json", json.dumps(structure, indent=2, sort_keys=True) + "\n")
            write("08_compose_services.txt", "\n".join(structure["service_names"]) + "\n")
        except InventoryError as exc:
            write(
                "09_compose_structure.json",
                json.dumps({"result": exc.code, "error": "compose_parse_fail"}, sort_keys=True) + "\n",
            )
            write("08_compose_services.txt", "UNKNOWN\n")
    else:
        fp.append("compose_sha256=UNKNOWN")
        fp.append("compose_file=MISSING")
        write(
            "09_compose_structure.json",
            json.dumps({"result": "FAIL", "error": "compose_missing"}, sort_keys=True) + "\n",
        )
        write("08_compose_services.txt", "UNKNOWN\n")
    req = app / "backend" / "requirements.txt"
    if req.is_file():
        r, o, e = run(["sha256sum", str(req)])
        fp.append(f"requirements_sha256={v_sha256(o.split()[0] if r == 0 and o else '')}")
    write("05_fingerprints.txt", "\n".join(fp) + "\n")

    # Images — only verified project services; typed fields only
    image_lines = ["scope=verified_project_services_only", f"project={expected_project_v}"]
    for logical, cname in verified_containers.items():
        r, o, e = run(
            [
                "docker",
                "inspect",
                cname,
                "--format",
                "{{.Image}} {{.Config.Image}}",
            ]
        )
        if r != 0:
            image_lines.append(
                f"{logical} container={cname} image_id=UNKNOWN config_image=UNKNOWN "
                f"RepoDigests=UNKNOWN RepoTags=UNKNOWN result=FAIL"
            )
            summary[f"{logical}_image_id"] = "UNKNOWN"
            if logical in ("backend", "frontend"):
                summary[f"{logical}_repo_digest"] = "UNKNOWN"
            continue
        parts = o.strip().split()
        image_id = v_image_id(parts[0] if parts else "")
        config_image = v_image_ref(parts[1] if len(parts) > 1 else "")
        digests = "UNKNOWN"
        tags = "UNKNOWN"
        result = "FAIL"
        if image_id != "UNKNOWN":
            r2, o2, e2 = run(
                [
                    "docker",
                    "image",
                    "inspect",
                    image_id,
                    "--format",
                    "{{json .RepoDigests}}|||{{json .RepoTags}}",
                ]
            )
            if r2 == 0 and "|||" in o2:
                d_raw, t_raw = o2.strip().split("|||", 1)
                digests = v_repo_digests(d_raw)
                tags = v_repo_tags(t_raw)
                result = "PASS" if digests != "UNKNOWN" or tags != "UNKNOWN" or image_id != "UNKNOWN" else "FAIL"
        image_lines.append(
            f"{logical} container={cname} image_id={image_id} config_image={config_image} "
            f"RepoDigests={digests} RepoTags={tags} result={result}"
        )
        summary[f"{logical}_image_id"] = image_id
        if logical in ("backend", "frontend"):
            summary[f"{logical}_repo_digest"] = digests
    write("06_images.txt", "\n".join(image_lines) + "\n")

    # Volumes/mounts — only verified containers
    mount_lines = ["scope=verified_project_containers_only"]
    for logical, cname in verified_containers.items():
        r, o, e = run(
            [
                "docker",
                "inspect",
                cname,
                "--format",
                "{{range .Mounts}}{{println .Type .Name .Source .Destination}}{{end}}",
            ]
        )
        if r != 0:
            mount_lines.append(f"{logical} container={cname} mounts=FAIL")
            continue
        mount_lines.append(f"{logical} container={cname}")
        for line in o.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                mtype = v_mount_type(parts[0])
                name = v_docker_name(parts[1]) if parts[1] not in {"", "<none>"} else "n/a"
                dest = v_mount_dest(parts[3])
                src_out = name if mtype == "volume" else "<bind_path>"
                mount_lines.append(
                    f"  type={mtype} volume_name={name} source={src_out} destination={dest}"
                )
            elif line.strip():
                mount_lines.append("  mount=UNKNOWN")
    r, o, e = run(["docker", "volume", "ls", "--format", "{{.Name}}\t{{.Driver}}"])
    vol_lines = ["named_volumes_project_scoped=begin"]
    if r != 0:
        vol_lines.append("volume_ls=FAIL")
    else:
        matched = 0
        for line in o.splitlines():
            name = v_docker_name(line.split("\t", 1)[0])
            if name == "UNKNOWN":
                continue
            if expected_project_v in name or name.endswith("_pgdata") or "pgdata" in name:
                driver = line.split("\t", 1)[1] if "\t" in line else "UNKNOWN"
                driver_v = validate_or_unknown(
                    driver, kind="driver", max_len=32, pattern=re.compile(r"^[A-Za-z0-9_-]{1,32}$")
                )
                vol_lines.append(f"{name}\t{driver_v}")
                matched += 1
        if matched == 0:
            vol_lines.append("project_volumes=UNKNOWN")
    vol_lines.append("named_volumes_project_scoped=end")
    write("10_volumes_mounts.txt", "\n".join(mount_lines + vol_lines) + "\n")

    # Env NAMES only from verified backend container
    env_lines = ["scope=verified_backend_only", "values=REDACTED"]
    backend_c = verified_containers["backend"]
    r, o, e = run(["docker", "inspect", backend_c, "--format", "{{range .Config.Env}}{{println .}}{{end}}"])
    ev_pack = "no"
    if r != 0:
        env_lines.append("backend_env=FAIL")
        summary["ev_pack_env_names_present"] = "UNKNOWN"
    else:
        names = []
        for line in o.splitlines():
            if not line.strip():
                continue
            name = v_env_name(line.split("=", 1)[0])
            if name == "UNKNOWN":
                continue
            names.append(name)
            env_lines.append(f"{name}=<redacted>")
        if any(n.startswith(("EV_PACK_", "EV_TOOL_", "EV_RUNTIME_", "EV_ARTIFACTS_")) for n in names):
            ev_pack = "yes"
        summary["ev_pack_env_names_present"] = ev_pack
    write("12_env_names.txt", "\n".join(env_lines) + "\n")

    # Health — in-memory parse; validated URL labels only (fixed allowlist)
    default_health = [
        "http://127.0.0.1:8080/health",
        "http://127.0.0.1:8000/health",
        "https://sateye.xdgen.com/health",
    ]
    health_urls = health_urls or default_health
    allowed_health = set(default_health)
    health_lines = []
    for url in health_urls:
        if url not in allowed_health:
            health_lines.append("url=UNKNOWN http=UNKNOWN fields={\"parse\":\"FAIL\",\"status\":\"UNKNOWN\"}")
            continue
        r, o, e = run(["curl", "-sS", "-m", "8", "-w", "\n__HTTP__%{http_code}", url])
        if r != 0:
            health_lines.append(
                f"{url} http=ERR fields={{\"parse\":\"FAIL\",\"status\":\"UNKNOWN\"}}"
            )
            continue
        if "__HTTP__" in o:
            body, _, code = o.rpartition("__HTTP__")
            code = v_http_code(code.strip())
        else:
            body, code = o, "UNKNOWN"
        fields = allowlisted_health_fields(body.strip())
        health_lines.append(
            f"{url} http={code} fields={json.dumps(fields, separators=(',', ':'), sort_keys=True)}"
        )
    write("11_health.txt", "\n".join(health_lines) + "\n")

    probe_lines = [f"commit={summary['live_commit']}"]
    probe_lines.append(f"baseline_ancestor={summary['baseline_1e71b7a_ancestor']}")
    for label, url in [
        ("local_tools_runtime", "http://127.0.0.1:8000/api/v1/tools/runtime"),
        ("public_tools_runtime", "https://sateye.xdgen.com/api/v1/tools/runtime"),
        ("public_composites", "https://sateye.xdgen.com/api/v1/analytics/composites"),
    ]:
        r, o, e = run(["curl", "-sS", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}", url])
        code = v_http_code(o.strip() if r == 0 and o.strip() else "UNKNOWN")
        if r != 0:
            code = "ERR"
        probe_lines.append(f"{label}_http={code}")
        if label == "public_tools_runtime":
            summary["tools_runtime_http"] = code
        if label == "public_composites":
            summary["composites_http"] = code
    write("14_baseline_and_config.txt", "\n".join(probe_lines) + "\n")

    if include_runner_checks:
        runner_lines = [f"hostname={summary['hostname']}", "gh_auth_status=omitted"]
        r, o, e = run(["gh", "api", "repos/techadv50-boop/EarthVision_Enterprise/actions/runners"])
        perm = scrub_gh_error(e, r)
        perm["permission"] = v_enum(perm.get("permission"), PERM_ALLOW)
        perm["http"] = v_http_code(perm.get("http", "UNKNOWN"))
        if r == 0:
            filtered = filter_runner_json(o)
            runner_lines.append(
                f"runners_api={json.dumps({'permission': perm, 'data': filtered}, separators=(',',':'), sort_keys=True)}"
            )
            statuses = []
            for rr in filtered.get("runners") or []:
                if "sateye-live" in (rr.get("labels") or []):
                    st = v_runner_status(rr.get("status"))
                    if st != "UNKNOWN":
                        statuses.append(st)
            summary["runner_status"] = ",".join(statuses) if statuses else "UNKNOWN"
        else:
            runner_lines.append(f"runners_api={json.dumps(perm, separators=(',',':'), sort_keys=True)}")
            summary["runner_status"] = "UNKNOWN"
            summary["actions_runs_api"] = perm.get("permission", "error")

        tip_for_api = approved_tip_v if approved_tip_v != "UNKNOWN" else approved_tip
        r2, o2, e2 = run(
            [
                "gh",
                "api",
                f"repos/techadv50-boop/EarthVision_Enterprise/actions/runs?head_sha={tip_for_api}&per_page=20",
            ]
        )
        perm2 = scrub_gh_error(e2, r2)
        perm2["permission"] = v_enum(perm2.get("permission"), PERM_ALLOW)
        perm2["http"] = v_http_code(perm2.get("http", "UNKNOWN"))
        if r2 == 0:
            filtered_runs = filter_actions_runs(o2, tip_for_api)
            runner_lines.append(
                f"actions_runs={json.dumps({'permission': perm2, 'data': filtered_runs}, separators=(',',':'), sort_keys=True)}"
            )
            summary["actions_runs_api"] = "ok"
        else:
            runner_lines.append(f"actions_runs={json.dumps(perm2, separators=(',',':'), sort_keys=True)}")
            summary["actions_runs_api"] = perm2.get("permission", "error")
        runner_lines.append("forbidden_not_run=workflow_dispatch")
        write("13_runner.txt", "\n".join(runner_lines) + "\n")
    else:
        write("13_runner.txt", "include_runner_checks=no\n")
        summary["runner_status"] = "skipped"
        summary["actions_runs_api"] = "skipped"

    write(
        "07_rollback.txt",
        "\n".join(
            [
                f"PRIOR_GIT_SHA={summary['live_commit']}",
                f"backend_image_id={summary.get('backend_image_id', 'UNKNOWN')}",
                f"frontend_image_id={summary.get('frontend_image_id', 'UNKNOWN')}",
                f"proxy_image_id={summary.get('proxy_image_id', 'UNKNOWN')}",
                "NOTE=Rollback availability = whether these image IDs remain in local docker image store.",
                "preserve_dir_check=operator_manual",
            ]
        )
        + "\n",
    )

    # Finalize summary + manifest BEFORE archive; both required for share_safe archive
    combined = "\n".join(v for k, v in files.items() if k in APPROVED_ARCHIVE_FILES or k.startswith("0"))
    # include all current approved content
    combined = "\n".join(files[k] for k in sorted(files) if k in APPROVED_ARCHIVE_FILES or k in files)
    try:
        hits = scan_for_secrets(combined)
        scanner_ok = True
    except Exception as exc:  # pragma: no cover
        hits = ["scanner_exception"]
        scanner_ok = False

    share_safe = scanner_ok and not hits and summary["identity_result"] == "PASS"
    summary["share_safe"] = "yes" if share_safe else "no"
    summary["identity_result"] = v_enum(summary["identity_result"], IDENTITY_ALLOW)
    write("00_return_summary.txt", _format_summary(summary))

    approved_count = sum(1 for k in files if k in APPROVED_ARCHIVE_FILES)
    manifest = [
        f"e19c_inventory_complete={'1' if summary['identity_result']=='PASS' else '0'}",
        f"identity_result={summary['identity_result']}",
        f"share_safe={summary['share_safe']}",
        f"secret_scanner={'OK' if scanner_ok else 'FAIL'}",
        f"secret_hits={','.join(hits) if hits else 'none'}",
        f"archive_allowed={'yes' if share_safe else 'no'}",
        f"approved_file_count={approved_count}",
        f"approved_files={','.join(sorted(k for k in files if k in APPROVED_ARCHIVE_FILES))}",
    ]
    write("15_manifest.txt", "\n".join(manifest) + "\n")

    if not share_safe:
        write(
            "STOP_SECRETS.txt",
            "SHARE_BLOCKED: secret scanner failed or detected sensitive content, "
            "or identity not PASS; do not archive or share this bundle\n"
            f"hits={hits if hits else 'none'}\n",
        )

    archive_path = None
    if share_safe:
        # Re-scan after summary/manifest finalized
        combined2 = "\n".join(files[k] for k in sorted(files) if k in APPROVED_ARCHIVE_FILES)
        hits2 = scan_for_secrets(combined2)
        if hits2:
            share_safe = False
            summary["share_safe"] = "no"
            write("00_return_summary.txt", _format_summary(summary))
            write(
                "15_manifest.txt",
                files["15_manifest.txt"].rstrip() + "\narchive_allowed=no\narchive=blocked_rescan\n",
            )
            write(
                "STOP_SECRETS.txt",
                "SHARE_BLOCKED: post-summary secret rescan failed\n",
            )
        else:
            archive_path, arch_result = build_allowlisted_archive(out_path, files)
            if arch_result != "OK" or not archive_path:
                share_safe = False
                summary["share_safe"] = "no"
                write("00_return_summary.txt", _format_summary(summary))
                write(
                    "15_manifest.txt",
                    files["15_manifest.txt"].rstrip() + "\narchive=FAIL\narchive_allowed=no\n",
                )
                write("STOP_SECRETS.txt", "SHARE_BLOCKED: archive creation or member verification failed\n")
                archive_path = None
            else:
                write(
                    "15_manifest.txt",
                    files["15_manifest.txt"].rstrip()
                    + f"\narchive={archive_path}\narchive_mode=0600\narchive_members_verified=yes\n",
                )

    return InventoryResult(
        status="OK" if summary["identity_result"] == "PASS" else "STOP",
        files=files,
        summary=summary,
        share_safe=share_safe,
        stop_reason=None,
        archive_path=archive_path,
    )


def _format_summary(summary: dict[str, str]) -> str:
    order = [
        "hostname",
        "compose_project",
        "app_dir",
        "identity_result",
        "live_branch",
        "live_commit",
        "baseline_1e71b7a_ancestor",
        "backend_image_id",
        "backend_repo_digest",
        "frontend_image_id",
        "frontend_repo_digest",
        "proxy_image_id",
        "env_sha256",
        "compose_sha256",
        "runner_status",
        "actions_runs_api",
        "tools_runtime_http",
        "composites_http",
        "ev_pack_env_names_present",
        "share_safe",
        "changes_made",
    ]
    lines = [f"{k}={summary.get(k, 'UNKNOWN')}" for k in order]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import sys

    include = os.environ.get("INCLUDE_RUNNER_CHECKS", "1") == "1"
    out_dir = os.environ.get("OUT_DIR") or ""
    app_dir = os.environ.get("APP_DIR") or "/opt/earthvision"
    result = run_inventory(
        app_dir=app_dir,
        out_dir=out_dir,
        expected_host=os.environ.get("EXPECTED_HOST", "zhzh"),
        expected_project=os.environ.get("EXPECTED_PROJECT", "sateye-fz2ic4"),
        expected_baseline=os.environ.get(
            "EXPECTED_BASELINE", "1e71b7abaa0fa8d4b70225d949afc8ae79923bb6"
        ),
        approved_tip=os.environ.get(
            "APPROVED_TIP", "e3012ce0a26e049d0af981d5994d0d829c3b647e"
        ),
        include_runner_checks=include,
    )
    print(f"[e19c] status={result.status} share_safe={result.share_safe}")
    if result.stop_reason:
        print(f"[e19c] {result.stop_reason}", file=sys.stderr)
    if result.status == "STOP":
        return 2
    if result.status == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
