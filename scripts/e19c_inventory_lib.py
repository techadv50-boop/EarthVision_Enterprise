#!/usr/bin/env python3
"""E1.9C-R1 inventory library: allowlisted, secret-safe structural capture.

Used by scripts/e19c_operator_inventory.sh and adversarial tests.
Never prints environment values, connection strings, tokens, or private keys.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
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

SENSITIVE_KEY = re.compile(
    r"(PASSWORD|SECRET|TOKEN|PRIVATE|API[_-]?KEY|AUTH|CREDENTIAL|DATABASE_URL|"
    r"POSTGRES|REDIS_URL|CONNECTION_STRING|ADMIN_PASS|JWT|SESSION|SMTP|"
    r"AWS_|GCP_|GOOGLE_|PRIVATE_KEY|PUBLISHER.*KEY|BEGIN\s)",
    re.I,
)
# DB/broker URIs only — do not treat http(s) health URLs as secrets.
CONN_URI = re.compile(r"(?i)\b(postgres|postgresql|redis|mysql|mongodb|amqp)://\S+")
SECRETISH = re.compile(r"(?i)(password|secret|token|private[_-]?key|bearer\s+[a-z0-9\.\-_]+)")
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
        rows.append(
            {
                "name": parts[0],
                "project": parts[1],
                "service": parts[2],
                "status": parts[3],
                "image": parts[4],
            }
        )
    return rows


def verify_project_services(
    rows: list[dict[str, str]],
    expected_project: str,
) -> dict[str, Any]:
    """Require backend, frontend, proxy containers labeled with expected_project."""
    in_project = [r for r in rows if r.get("project") == expected_project]
    other_projects = sorted({r["project"] for r in rows if r.get("project") and r["project"] != expected_project})

    found: dict[str, dict[str, str]] = {}
    for logical, aliases in APP_SERVICE_ALIASES.items():
        matches = [r for r in in_project if r.get("service") in aliases]
        if matches:
            found[logical] = matches[0]
        else:
            found[logical] = {}

    missing = [s for s in REQUIRED_SERVICES if not found[s]]
    result = {
        "expected_project": expected_project,
        "containers_in_project": [
            {"name": r["name"], "service": r["service"], "status": r["status"], "image": r["image"]}
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
    """Parse health JSON in-memory; keep only allowlisted keys."""
    try:
        data = json.loads(body)
    except Exception:
        return {"parse": "FAIL", "status": "UNKNOWN"}
    if not isinstance(data, dict):
        return {"parse": "FAIL", "status": "UNKNOWN"}
    out: dict[str, Any] = {"parse": "OK"}
    for key in ("status", "version", "environment", "database"):
        if key not in data:
            continue
        val = data[key]
        if val is None or isinstance(val, (str, int, float, bool)):
            if isinstance(val, str) and (len(val) > 80 or SECRETISH.search(val) or CONN_URI.search(val)):
                out[key] = "REDACTED"
            else:
                out[key] = val
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
    """Keep allowlisted runner fields only."""
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
    for r in runners:
        if not isinstance(r, dict):
            continue
        labels = []
        for lab in r.get("labels") or []:
            if isinstance(lab, dict) and "name" in lab:
                labels.append(str(lab["name"]))
            elif isinstance(lab, str):
                labels.append(lab)
        out.append(
            {
                "name": str(r.get("name") or "UNKNOWN"),
                "id": r.get("id", "UNKNOWN"),
                "status": str(r.get("status") or "UNKNOWN"),
                "busy": r.get("busy", "UNKNOWN"),
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
    keep = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        head = str(r.get("head_sha") or "")
        if head and head != expected_sha:
            continue
        path = str(r.get("path") or "")
        name = str(r.get("name") or "")
        keep.append(
            {
                "name": name,
                "path": path.split("/")[-1] if path else "UNKNOWN",
                "head_sha": head or "UNKNOWN",
                "status": str(r.get("status") or "UNKNOWN"),
                "conclusion": str(r.get("conclusion") or "UNKNOWN"),
                "event": str(r.get("event") or "UNKNOWN"),
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
        files[name] = content
        (out_path / name).write_text(content, encoding="utf-8")

    host = hostname_value if hostname_value is not None else (run(["hostname"])[1].strip() or "UNKNOWN")
    summary["hostname"] = host or "UNKNOWN"
    identity_lines = [
        f"captured_at=UNKNOWN",  # filled below
        f"hostname={summary['hostname']}",
        f"app_dir={app_dir}",
        f"app_dir_exists={'1' if Path(app_dir).is_dir() else '0'}",
        f"expected_host={expected_host}",
        f"expected_project={expected_project}",
        f"approved_tip={approved_tip}",
        f"expected_baseline={expected_baseline}",
    ]
    from datetime import datetime, timezone

    identity_lines[0] = f"captured_at={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"

    # --- HARD IDENTITY GATE (must pass before any further inventory) ---
    if summary["hostname"] != expected_host:
        reason = f"STOP: hostname {summary['hostname']} != expected {expected_host}"
        identity_lines.append("identity_result=STOP")
        identity_lines.append(f"stop_reason={reason}")
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        write("00_return_summary.txt", _format_summary(summary))
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    if not Path(app_dir).is_dir():
        reason = f"STOP: APP_DIR missing: {app_dir}"
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
    svc_check = verify_project_services(rows, expected_project)
    write("02_project_services.json", json.dumps(svc_check, indent=2) + "\n")

    if svc_check["missing_required"]:
        reason = (
            "STOP: required services missing from project "
            f"{expected_project}: {','.join(svc_check['missing_required'])}"
        )
        identity_lines.append("identity_result=STOP")
        identity_lines.append(f"missing_required={','.join(svc_check['missing_required'])}")
        # Explicitly note that other projects on host do not satisfy identity
        if svc_check["other_projects_present"]:
            identity_lines.append(
                "other_projects_ignored=" + ",".join(svc_check["other_projects_present"])
            )
        write("01_identity.txt", "\n".join(identity_lines) + "\n")
        write("STOP.txt", reason + "\n")
        summary["identity_result"] = "STOP"
        summary["compose_project"] = expected_project
        write("00_return_summary.txt", _format_summary(summary))
        # CRITICAL: do not continue inventory
        return InventoryResult(status="STOP", files=files, summary=summary, share_safe=False, stop_reason=reason)

    identity_lines.append("identity_result=PASS")
    identity_lines.append(f"compose_project={expected_project}")
    for logical in REQUIRED_SERVICES:
        info = svc_check["required"][logical]
        identity_lines.append(
            f"{logical}_container={info['container']}|service={info['service_label']}|status={info['status']}"
        )
    write("01_identity.txt", "\n".join(identity_lines) + "\n")
    summary["identity_result"] = "PASS"
    summary["compose_project"] = expected_project

    verified_containers = {
        logical: svc_check["required"][logical]["container"] for logical in REQUIRED_SERVICES
    }
    verified_names = set(verified_containers.values())

    # --- Git (read-only) ---
    git: dict[str, str] = {}
    app = Path(app_dir)
    if (app / ".git").exists():
        def git_out(args: list[str]) -> str:
            r, o, e = run(["git", "-C", app_dir, *args])
            return o.strip() if r == 0 else ""

        branch = git_out(["branch", "--show-current"]) or "UNKNOWN"
        commit = git_out(["rev-parse", "HEAD"]) or "UNKNOWN"
        short = git_out(["rev-parse", "--short", "HEAD"]) or "UNKNOWN"
        status_sb = git_out(["status", "-sb"]).splitlines()[0] if git_out(["status", "-sb"]) else "UNKNOWN"
        baseline_ancestor = "UNKNOWN"
        r, o, e = run(["git", "-C", app_dir, "cat-file", "-e", f"{expected_baseline}^{{commit}}"])
        if r == 0:
            r2, _, _ = run(["git", "-C", app_dir, "merge-base", "--is-ancestor", expected_baseline, "HEAD"])
            baseline_ancestor = "yes" if r2 == 0 else "no"
        else:
            baseline_ancestor = "object_missing"
        tip_eq = "yes" if commit == approved_tip else "no"
        git = {
            "branch": branch,
            "commit": commit,
            "commit_short": short,
            "status_summary": status_sb,
            "baseline_1e71b7a_ancestor": baseline_ancestor,
            "live_equals_approved_tip_e3012ce": tip_eq,
        }
    else:
        git = {
            "branch": "UNKNOWN",
            "commit": "UNKNOWN",
            "commit_short": "UNKNOWN",
            "status_summary": "UNKNOWN",
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
        fp.append(f"env_size={env_path.stat().st_size}")
        r, o, e = run(["sha256sum", str(env_path)])
        fp.append(f"env_sha256={o.split()[0] if r == 0 and o else 'UNKNOWN'}")
        summary["env_sha256"] = fp[-1].split("=", 1)[1]
    else:
        fp.append("env_present=0")
        fp.append("env_sha256=UNKNOWN")
    compose_path = app / compose_file_name
    if compose_path.is_file():
        r, o, e = run(["sha256sum", str(compose_path)])
        fp.append(f"compose_sha256={o.split()[0] if r == 0 and o else 'UNKNOWN'}")
        summary["compose_sha256"] = fp[-1].split("=", 1)[1]
        # Structural parse of FILE (not docker compose config)
        try:
            structure = parse_compose_structure(compose_path.read_text(encoding="utf-8", errors="replace"))
            write("09_compose_structure.json", json.dumps(structure, indent=2) + "\n")
            write("08_compose_services.txt", "\n".join(structure["service_names"]) + "\n")
        except InventoryError as exc:
            write("09_compose_structure.json", json.dumps({"result": exc.code, "error": str(exc)}) + "\n")
            write("08_compose_services.txt", "UNKNOWN\n")
    else:
        fp.append("compose_sha256=UNKNOWN")
        fp.append("compose_file=MISSING")
        write("09_compose_structure.json", json.dumps({"result": "FAIL", "error": "compose_missing"}) + "\n")
        write("08_compose_services.txt", "UNKNOWN\n")
    req = app / "backend" / "requirements.txt"
    if req.is_file():
        r, o, e = run(["sha256sum", str(req)])
        fp.append(f"requirements_sha256={o.split()[0] if r == 0 and o else 'UNKNOWN'}")
    write("05_fingerprints.txt", "\n".join(fp) + "\n")

    # Images — only verified project services
    image_lines = ["scope=verified_project_services_only", f"project={expected_project}"]
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
            image_lines.append(f"{logical} container={cname} image_id=UNKNOWN repo_tags=UNKNOWN result=FAIL")
            summary[f"{logical}_image_id"] = "UNKNOWN"
            if logical in ("backend", "frontend"):
                summary[f"{logical}_repo_digest"] = "UNKNOWN"
            continue
        parts = o.strip().split()
        image_id = parts[0] if parts else "UNKNOWN"
        config_image = parts[1] if len(parts) > 1 else "UNKNOWN"
        # Repo digests from image id
        r2, o2, e2 = run(
            [
                "docker",
                "image",
                "inspect",
                image_id,
                "--format",
                "{{json .RepoDigests}} {{json .RepoTags}} {{.Created}} {{.Id}}",
            ]
        )
        if r2 != 0:
            image_lines.append(
                f"{logical} container={cname} image_id={image_id} config_image={config_image} "
                f"RepoDigests=UNKNOWN RepoTags=UNKNOWN result=FAIL"
            )
            summary[f"{logical}_image_id"] = image_id
            if logical in ("backend", "frontend"):
                summary[f"{logical}_repo_digest"] = "UNKNOWN"
        else:
            image_lines.append(
                f"{logical} container={cname} image_id={image_id} config_image={config_image} inspect={o2.strip()} result=PASS"
            )
            summary[f"{logical}_image_id"] = image_id
            # extract digests JSON first token
            digest_m = re.search(r"(\[[^\]]*\])", o2)
            if logical in ("backend", "frontend"):
                summary[f"{logical}_repo_digest"] = digest_m.group(1) if digest_m else "UNKNOWN"
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
                mtype, name, source, dest = parts[0], parts[1], parts[2], parts[3]
                # Do not recurse into source; for binds record path but not contents
                src_out = name if mtype == "volume" else "<bind_path>"
                mount_lines.append(f"  type={mtype} volume_name={name or 'n/a'} source={src_out} destination={dest}")
            elif line.strip():
                mount_lines.append("  mount=UNKNOWN")
    # Named volumes filtered by project prefix when possible
    r, o, e = run(["docker", "volume", "ls", "--format", "{{.Name}}\t{{.Driver}}"])
    vol_lines = ["=== named_volumes (project-scoped filter) ==="]
    if r != 0:
        vol_lines.append("volume_ls=FAIL")
    else:
        matched = 0
        for line in o.splitlines():
            name = line.split("\t", 1)[0]
            if expected_project in name or name.endswith("_pgdata") or "pgdata" in name:
                vol_lines.append(line)
                matched += 1
        if matched == 0:
            vol_lines.append("project_volumes=UNKNOWN")
    write("10_volumes_mounts.txt", "\n".join(mount_lines + vol_lines) + "\n")

    # Env NAMES only from verified backend container (docker inspect Config.Env → names)
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
            name = line.split("=", 1)[0]
            names.append(name)
            env_lines.append(f"{name}=<redacted>")
        if any(n.startswith(("EV_PACK_", "EV_TOOL_", "EV_RUNTIME_", "EV_ARTIFACTS_")) for n in names):
            ev_pack = "yes"
        summary["ev_pack_env_names_present"] = ev_pack
    write("12_env_names.txt", "\n".join(env_lines) + "\n")

    # Health — no body files on disk; parse in memory
    health_urls = health_urls or [
        "http://127.0.0.1:8080/health",
        "http://127.0.0.1:8000/health",
        "https://sateye.xdgen.com/health",
    ]
    health_lines = []
    for url in health_urls:
        # Use curl writing body to stdout only; captured by subprocess memory
        r, o, e = run(["curl", "-sS", "-m", "8", "-w", "\n__HTTP__%{http_code}", url])
        if r != 0:
            health_lines.append(f"{url} http=ERR fields={{\"parse\":\"FAIL\",\"status\":\"UNKNOWN\"}}")
            continue
        if "__HTTP__" in o:
            body, _, code = o.rpartition("__HTTP__")
            code = code.strip()
        else:
            body, code = o, "UNKNOWN"
        fields = allowlisted_health_fields(body.strip())
        health_lines.append(f"{url} http={code} fields={json.dumps(fields, separators=(',', ':'))}")
    write("11_health.txt", "\n".join(health_lines) + "\n")

    # Baseline / endpoint probes (status codes only)
    probe_lines = [f"commit={summary['live_commit']}"]
    probe_lines.append(f"baseline_ancestor={summary['baseline_1e71b7a_ancestor']}")
    for label, url in [
        ("local_tools_runtime", "http://127.0.0.1:8000/api/v1/tools/runtime"),
        ("public_tools_runtime", "https://sateye.xdgen.com/api/v1/tools/runtime"),
        ("public_composites", "https://sateye.xdgen.com/api/v1/analytics/composites"),
    ]:
        r, o, e = run(["curl", "-sS", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}", url])
        code = o.strip() if r == 0 and o.strip() else "UNKNOWN"
        if r != 0:
            code = "ERR"
        probe_lines.append(f"{label}_http={code}")
        if label == "public_tools_runtime":
            summary["tools_runtime_http"] = code
        if label == "public_composites":
            summary["composites_http"] = code
    write("14_baseline_and_config.txt", "\n".join(probe_lines) + "\n")

    # Runner checks — allowlisted only
    if include_runner_checks:
        runner_lines = [f"hostname={summary['hostname']}", "gh_auth_status=omitted"]
        r, o, e = run(["gh", "api", "repos/techadv50-boop/EarthVision_Enterprise/actions/runners"])
        perm = scrub_gh_error(e, r)
        if r == 0:
            filtered = filter_runner_json(o)
            runner_lines.append(f"runners_api={json.dumps({'permission': perm, 'data': filtered}, separators=(',',':'))}")
            # derive status for expected label
            statuses = []
            for rr in filtered.get("runners") or []:
                if "sateye-live" in (rr.get("labels") or []):
                    statuses.append(str(rr.get("status")))
            summary["runner_status"] = ",".join(statuses) if statuses else "UNKNOWN"
        else:
            runner_lines.append(f"runners_api={json.dumps(perm, separators=(',',':'))}")
            summary["runner_status"] = "UNKNOWN"
            summary["actions_runs_api"] = perm.get("permission", "error")

        r2, o2, e2 = run(
            [
                "gh",
                "api",
                f"repos/techadv50-boop/EarthVision_Enterprise/actions/runs?head_sha={approved_tip}&per_page=20",
            ]
        )
        perm2 = scrub_gh_error(e2, r2)
        if r2 == 0:
            filtered_runs = filter_actions_runs(o2, approved_tip)
            runner_lines.append(
                f"actions_runs={json.dumps({'permission': perm2, 'data': filtered_runs}, separators=(',',':'))}"
            )
            summary["actions_runs_api"] = "ok"
        else:
            runner_lines.append(f"actions_runs={json.dumps(perm2, separators=(',',':'))}")
            summary["actions_runs_api"] = perm2.get("permission", "error")
        runner_lines.append("forbidden_not_run=workflow_dispatch")
        write("13_runner.txt", "\n".join(runner_lines) + "\n")
    else:
        write("13_runner.txt", "include_runner_checks=no\n")
        summary["runner_status"] = "skipped"
        summary["actions_runs_api"] = "skipped"

    # Rollback note (no full image dump)
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

    # Secret scan across outputs — required for share_safe
    combined = "\n".join(files.values())
    try:
        hits = scan_for_secrets(combined)
        scanner_ok = True
    except Exception as exc:  # pragma: no cover
        hits = [f"scanner_exception:{exc}"]
        scanner_ok = False

    share_safe = scanner_ok and not hits
    summary["share_safe"] = "yes" if share_safe else "no"
    write("00_return_summary.txt", _format_summary(summary))

    manifest = [
        f"e19c_inventory_complete={'1' if summary['identity_result']=='PASS' else '0'}",
        f"identity_result={summary['identity_result']}",
        f"share_safe={summary['share_safe']}",
        f"secret_scanner={'OK' if scanner_ok else 'FAIL'}",
        f"secret_hits={','.join(hits) if hits else 'none'}",
        f"archive_allowed={'yes' if share_safe else 'no'}",
        f"file_count={len(files)}",
    ]
    write("15_manifest.txt", "\n".join(manifest) + "\n")

    if not share_safe:
        write(
            "STOP_SECRETS.txt",
            "SHARE_BLOCKED: secret scanner failed or detected sensitive content; "
            "do not archive or share this bundle\n"
            f"hits={hits}\n",
        )

    # Archive only when share_safe
    archive_path = None
    if share_safe:
        archive_path = out_path.parent / f"{out_path.name}.tar.gz"
        r, o, e = run(["tar", "-C", str(out_path.parent), "-czf", str(archive_path), out_path.name])
        if r != 0:
            write("15_manifest.txt", files["15_manifest.txt"] + "archive=FAIL\n")
            summary["share_safe"] = "no"
            share_safe = False
            write(
                "STOP_SECRETS.txt",
                "SHARE_BLOCKED: archive creation failed\n",
            )
        else:
            write("15_manifest.txt", files["15_manifest.txt"] + f"archive={archive_path}\n")

    return InventoryResult(
        status="OK" if summary["identity_result"] == "PASS" else "STOP",
        files=files,
        summary=summary,
        share_safe=share_safe,
        stop_reason=None,
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
