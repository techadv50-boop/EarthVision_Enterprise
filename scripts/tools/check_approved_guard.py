#!/usr/bin/env python3
"""Guard approved tools against silent path changes.

Compares git diff against the merge base (or BASE_SHA env) and fails when:
  - Any path owned by an approved tool changes, AND
  - That tool's version / approved_version was not bumped in tools/manifest.json

Also reminds that deploy remains full-app (not independent tool deploy).

Usage:
  python scripts/tools/check_approved_guard.py
  BASE_SHA=<sha> python scripts/tools/check_approved_guard.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "manifest.json"


def run_git(*args: str) -> str:
    out = subprocess.check_output(["git", *args], cwd=ROOT, text=True)
    return out.strip()


def changed_files(base: str) -> set[str]:
    # Include staged + unstaged + committed-since-base
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


def main() -> int:
    if not MANIFEST.is_file():
        print(f"ERROR: missing {MANIFEST}", file=sys.stderr)
        return 2

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("deployment_model") != "full_app_only":
        print(
            "ERROR: deployment_model must remain full_app_only — "
            "do not claim independent tool deployment",
            file=sys.stderr,
        )
        return 1

    base = os.environ.get("BASE_SHA") or os.environ.get("GITHUB_BASE_SHA")
    if not base:
        # Prefer baseline tag when present; else remote branch tip's parent discovery
        try:
            base = run_git("rev-parse", "sateye-baseline-20261012-1e71b7a^{commit}")
        except subprocess.CalledProcessError:
            try:
                base = run_git("merge-base", "HEAD", "origin/cursor/scene-download-eye-5d6d")
            except subprocess.CalledProcessError:
                base = run_git("rev-parse", "HEAD~1") if run_git("rev-list", "--count", "HEAD") != "1" else run_git("rev-parse", "HEAD")

    try:
        base_manifest_raw = run_git("show", f"{base}:tools/manifest.json")
        base_manifest = json.loads(base_manifest_raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        # First introduction of manifest — only enforce when base already has it
        print(
            f"APPROVED GUARD: base {base[:12]} has no tools/manifest.json yet "
            "(bootstrap OK). Full-app deploy model unchanged."
        )
        return 0

    changed = changed_files(base)
    if not changed:
        print("APPROVED GUARD: no file changes vs base")
        return 0

    base_by_key = {
        t.get("registry_key"): t for t in (base_manifest.get("tools") or [])
    }
    head_by_key = {t.get("registry_key"): t for t in (data.get("tools") or [])}

    errors: list[str] = []
    for key, head_tool in head_by_key.items():
        if head_tool.get("status") != "approved":
            continue
        paths = set(head_tool.get("paths") or [])
        touched = sorted(paths & changed)
        if not touched:
            continue
        base_tool = base_by_key.get(key) or {}
        version_bumped = head_tool.get("version") != base_tool.get("version")
        approved_bumped = head_tool.get("approved_version") != base_tool.get(
            "approved_version"
        )
        if not (version_bumped and approved_bumped):
            errors.append(
                f"approved tool '{key}' paths changed ({', '.join(touched)}) "
                f"without bumping version AND approved_version "
                f"(was {base_tool.get('version')}/{base_tool.get('approved_version')}, "
                f"now {head_tool.get('version')}/{head_tool.get('approved_version')})"
            )

    # Shared sensitive paths: require canary + approved tests to be listed (CI runs them)
    shared = set(data.get("shared_sensitive_paths") or [])
    shared_touched = sorted(shared & changed)
    if shared_touched:
        print(
            "APPROVED GUARD WARNING: shared sensitive paths changed:",
            ", ".join(shared_touched),
        )
        print(
            "  → CI must run approved + canary tool tests "
            "(full-app deploy still replaces entire image)."
        )

    if errors:
        print("APPROVED GUARD FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "  Note: this does NOT provide independent deployment; "
            "it only blocks silent regressions of approved tools.",
            file=sys.stderr,
        )
        return 1

    print(
        f"APPROVED GUARD OK vs {base[:12]} "
        f"(changed={len(changed)} files; full_app_only deploy model)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
