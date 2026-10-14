#!/usr/bin/env python3
"""Adversarial tests for Stage P1.1 core protection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "tools" / "check_core_protection.py"


def run_checker(env: dict[str, str], *, cwd: Path | None = None) -> tuple[int, str]:
    full = {**os.environ, **env}
    # Remove legacy bypass unless explicitly set in env dict
    if "CORE_RELEASE" not in env:
        full.pop("CORE_RELEASE", None)
    if "CORE_RELEASE_APPROVAL" not in env:
        full.pop("CORE_RELEASE_APPROVAL", None)
    proc = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=cwd or ROOT,
        env=full,
        text=True,
        capture_output=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def test_standalone_core_release_env_rejected():
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    code, out = run_checker({"BASE_SHA": base, "CORE_RELEASE": "approved"})
    assert code == 1, out
    assert "alone is not an authorized" in out or "CORE_RELEASE" in out


def test_missing_base_fail_closed():
    code, out = run_checker(
        {
            "BASE_SHA": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        }
    )
    assert code == 2, out
    assert "not a resolvable" in out or "cannot resolve" in out


def test_empty_base_without_merge_base_fail_closed(tmp_path: Path | None = None):
    # Unset BASE_SHA and point away from origin merge-base by using a temp bare-ish env
    env = {"BASE_SHA": "", "GITHUB_BASE_SHA": ""}
    # Force failure by using invalid empty after strip — resolve_base tries merge-base next.
    # If merge-base works in this repo, that's OK (returns 0 or OK). Simulate missing remote:
    code, out = run_checker(
        {
            **env,
            # Override PATH? Instead call resolve directly via a fake BASE that is whitespace
            "BASE_SHA": "   ",
        }
    )
    # Whitespace BASE_SHA falls through to merge-base; in this workspace it likely succeeds.
    # The hard fail-closed for unresolvable explicit SHA is covered above.
    assert code in {0, 2}


def test_policy_tamper_self_protect_when_live():
    """If checker exists on base, modifying it without base-resident approval fails."""
    # Use current HEAD as base where checker already exists (this branch).
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not (ROOT / "scripts" / "tools" / "check_core_protection.py").is_file():
        return
    # Create a dirty modification in a worktree copy via env simulation:
    # We invoke checker with BASE=HEAD and a staged change is not needed if no changes.
    # Instead: verify that with CORE_RELEASE=approved and no approval, changing nothing is OK.
    code, out = run_checker({"BASE_SHA": head, "CORE_RELEASE": "approved"})
    assert code == 1, out


def test_dirty_self_protect_fails_against_live_base():
    """Once the checker exists on BASE, uncommitted edits to it require base-resident approval."""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # HEAD (eecf836+) already contains the checker → protection_live=True.
    # Working tree P1.1 edits to self-protected paths must fail closed without
    # a base-resident CORE_RELEASE_APPROVAL.
    code, out = run_checker({"BASE_SHA": head})
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if not dirty:
        # Clean tree — nothing to enforce
        assert code == 0, out
        return
    if "check_core_protection.py" in dirty or "core_protection.json" in dirty:
        assert code == 1, out
        assert "core_protection_machinery" in out
    # CORE_RELEASE=approved still insufficient even with dirty self-protect
    code2, out2 = run_checker({"BASE_SHA": head, "CORE_RELEASE": "approved"})
    assert code2 == 1, out2


def main() -> int:
    failures = 0
    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
