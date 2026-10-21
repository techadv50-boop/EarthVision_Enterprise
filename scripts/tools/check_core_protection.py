#!/usr/bin/env python3
"""Reject unauthorized changes to Host Shell core modules (Stage P1.1).

Fail-closed rules:
  - Comparison base MUST be resolvable (BASE_SHA / GITHUB_BASE_SHA / merge-base).
  - ``CORE_RELEASE=approved`` alone is NEVER sufficient.
  - Core changes require an auditable approval record under ``tools/core_releases/``
    referenced by ``CORE_RELEASE_APPROVAL=<id>``.
  - Approvals that authorize changes to the protection machinery itself must
    already exist on the comparison base (cannot be introduced in the same PR).
  - Protection config, this checker, and the Tool Protection workflow are always
    treated as core (self-protecting) and are NOT plugin-safe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "tools" / "core_protection.json"
RELEASES_DIR = ROOT / "tools" / "core_releases"

# Always core — never grant via plugin_safe_paths_prefix alone.
SELF_PROTECTED = (
    "tools/core_protection.json",
    "scripts/tools/check_core_protection.py",
    ".github/workflows/tool-protection.yml",
    "tools/core_releases/",
)


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_ok(*args: str) -> bool:
    try:
        subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def resolve_base() -> str:
    """Resolve comparison base or raise SystemExit(2) fail-closed."""
    base = (os.environ.get("BASE_SHA") or os.environ.get("GITHUB_BASE_SHA") or "").strip()
    if base:
        if not git_ok("rev-parse", "--verify", f"{base}^{{commit}}"):
            print(
                f"CORE PROTECTION FAILED: BASE_SHA={base!r} is not a resolvable git commit",
                file=sys.stderr,
            )
            raise SystemExit(2)
        return run_git("rev-parse", f"{base}^{{commit}}")

    # Prefer explicit merge-base with locked production baseline branch.
    try:
        mb = run_git("merge-base", "HEAD", "origin/cursor/scene-download-eye-5d6d")
        if mb:
            return mb
    except subprocess.CalledProcessError:
        pass

    print(
        "CORE PROTECTION FAILED: cannot resolve comparison base "
        "(set BASE_SHA / GITHUB_BASE_SHA to a valid commit; "
        "refusing HEAD~1 fallback)",
        file=sys.stderr,
    )
    raise SystemExit(2)


def changed_files(base: str) -> set[str]:
    files: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", base],
        ["git", "diff", "--name-only", "--cached"],
    ):
        try:
            out = subprocess.check_output(cmd, cwd=ROOT, text=True).strip()
        except subprocess.CalledProcessError:
            continue
        if out:
            files.update(out.splitlines())
    return {f for f in files if f}


def path_matches(changed: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return changed == pattern.rstrip("/") or changed.startswith(pattern)
    return changed == pattern or changed.startswith(pattern + "/")


def is_self_protected(path: str) -> bool:
    return any(path_matches(path, p) for p in SELF_PROTECTED)


def existed_on_base(path: str, base: str) -> bool:
    return git_ok("cat-file", "-e", f"{base}:{path}")


def load_approval(approval_id: str, *, from_ref: str | None = None) -> dict:
    """Load approval JSON from working tree or from a git ref (base)."""
    rel = f"tools/core_releases/{approval_id}.json"
    if from_ref:
        try:
            raw = run_git("show", f"{from_ref}:{rel}")
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                f"approval {approval_id!r} not present on base {from_ref[:12]}"
            ) from exc
        data = json.loads(raw)
    else:
        path = ROOT / rel
        if not path.is_file():
            raise ValueError(f"approval file missing: {rel}")
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("approval must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError("approval schema_version must be 1")
    if data.get("approval_id") != approval_id:
        raise ValueError("approval_id mismatch vs filename")
    return data


def approval_covers(
    approval: dict,
    *,
    path: str,
    module_id: str | None,
    base: str,
) -> bool:
    """Return True if the approval authorizes this core path change."""
    # Bind approval to the comparison base (auditable release isolation).
    approved_base = str(approval.get("base_sha") or "").strip()
    if not approved_base:
        return False
    try:
        resolved = run_git("rev-parse", f"{approved_base}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    if resolved != base:
        return False

    expires = approval.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                return False
        except ValueError:
            return False

    allowed_modules = set(approval.get("allowed_modules") or [])
    allowed_paths = list(approval.get("allowed_paths") or [])
    if module_id and module_id in allowed_modules:
        return True
    if any(path_matches(path, p) for p in allowed_paths):
        return True
    if is_self_protected(path) and "core_protection_machinery" in allowed_modules:
        return True
    return False


def main() -> int:
    if not CORE.is_file():
        print(f"ERROR: missing {CORE}", file=sys.stderr)
        return 2

    data = json.loads(CORE.read_text(encoding="utf-8"))

    # Standalone env token must never bypass (even if still present in JSON for docs).
    legacy_env = os.environ.get("CORE_RELEASE", "")
    if legacy_env and not os.environ.get("CORE_RELEASE_APPROVAL"):
        print(
            "CORE PROTECTION FAILED: CORE_RELEASE env alone is not an authorized "
            "bypass (P1.1). Set CORE_RELEASE_APPROVAL=<id> referencing "
            "tools/core_releases/<id>.json",
            file=sys.stderr,
        )
        return 1

    try:
        base = resolve_base()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    changed = changed_files(base)
    if not changed:
        print(f"CORE PROTECTION OK (no file changes vs {base[:12]})")
        return 0

    safe_prefixes = list(data.get("plugin_safe_paths_prefix") or [])
    # Never treat self-protected paths as plugin-safe, even if misconfigured.
    safe_prefixes = [p for p in safe_prefixes if not any(
        path_matches(p.rstrip("/"), sp) or path_matches(sp.rstrip("/"), p)
        for sp in SELF_PROTECTED
    )]

    modules = data.get("modules") or []
    approval_id = (os.environ.get("CORE_RELEASE_APPROVAL") or "").strip()
    approval: dict | None = None
    approval_from_base: dict | None = None

    if approval_id:
        try:
            approval = load_approval(approval_id, from_ref=None)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"CORE PROTECTION FAILED: invalid approval: {exc}", file=sys.stderr)
            return 1
        # Self-protection: approval authorizing machinery changes must exist on base.
        try:
            approval_from_base = load_approval(approval_id, from_ref=base)
        except ValueError:
            approval_from_base = None

    violations: list[str] = []

    # Once the checker exists on the comparison base, self-protection is live.
    # Until then (introducing P1/P1.1 on a feature branch), bootstrap is allowed
    # so the machinery can land once — subsequent PRs cannot weaken it without
    # a base-resident approval.
    protection_live = existed_on_base("scripts/tools/check_core_protection.py", base)

    for path in sorted(changed):
        if is_self_protected(path):
            if not protection_live:
                continue
            if not approval_from_base or not approval_covers(
                approval_from_base, path=path, module_id="core_protection_machinery", base=base
            ):
                violations.append(
                    f"{path}  [module=core_protection_machinery] requires "
                    f"CORE_RELEASE_APPROVAL that already exists on base {base[:12]}"
                )
            continue

        if any(path_matches(path, p) for p in safe_prefixes):
            continue

        matched_module = None
        for mod in modules:
            patterns = mod.get("paths") or []
            if any(path_matches(path, p) for p in patterns):
                matched_module = mod.get("id")
                break
        if not matched_module:
            continue

        covered = bool(
            approval
            and approval_covers(approval, path=path, module_id=matched_module, base=base)
        )
        if not covered:
            violations.append(
                f"{path}  [module={matched_module}] requires auditable "
                f"CORE_RELEASE_APPROVAL bound to base_sha={base[:12]}"
            )

    if violations:
        print("CORE PROTECTION FAILED — unauthorized Host Shell core changes:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nCore changes require a separately authorized approval record under "
            "tools/core_releases/ (CORE_RELEASE_APPROVAL=<id>). "
            "CORE_RELEASE=approved alone is rejected.",
            file=sys.stderr,
        )
        return 1

    print(
        f"CORE PROTECTION OK ({len(changed)} changed file(s); base={base[:12]}; "
        f"approval={approval_id or 'none'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
