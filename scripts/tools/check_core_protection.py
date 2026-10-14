#!/usr/bin/env python3
"""Reject unauthorized changes to Host Shell core modules (Stage P1).

Fails when a diff touches protected core paths unless CORE_RELEASE=approved.
Plugin-safe path prefixes are always allowed without a core release.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "tools" / "core_protection.json"


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


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


def main() -> int:
    if not CORE.is_file():
        print(f"ERROR: missing {CORE}", file=sys.stderr)
        return 2

    data = json.loads(CORE.read_text(encoding="utf-8"))
    release_env = data.get("core_release_env") or "CORE_RELEASE"
    release_token = data.get("core_release_token") or "approved"
    core_ok = os.environ.get(release_env) == release_token

    base = os.environ.get("BASE_SHA") or os.environ.get("GITHUB_BASE_SHA")
    if not base:
        try:
            base = run_git("merge-base", "HEAD", "origin/cursor/scene-download-eye-5d6d")
        except subprocess.CalledProcessError:
            try:
                base = run_git("rev-parse", "HEAD~1")
            except subprocess.CalledProcessError:
                print("CORE PROTECTION: no base; nothing to compare")
                return 0

    changed = changed_files(base)
    if not changed:
        print("CORE PROTECTION: no file changes vs base")
        return 0

    safe_prefixes = list(data.get("plugin_safe_paths_prefix") or [])
    modules = data.get("modules") or []
    violations: list[str] = []

    for path in sorted(changed):
        if any(path_matches(path, p) for p in safe_prefixes):
            continue
        for mod in modules:
            patterns = mod.get("paths") or []
            if any(path_matches(path, p) for p in patterns):
                if not core_ok:
                    violations.append(
                        f"{path}  [module={mod.get('id')}] requires {release_env}={release_token}"
                    )
                break

    if violations:
        print("CORE PROTECTION FAILED — unauthorized Host Shell core changes:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            f"\nCore changes require a separately approved core release "
            f"({release_env}={release_token}). Plugin work must stay under "
            "plugin_safe_paths_prefix.",
            file=sys.stderr,
        )
        return 1

    print(
        f"CORE PROTECTION OK ({len(changed)} changed file(s); "
        f"core_release={'yes' if core_ok else 'not-requested'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
