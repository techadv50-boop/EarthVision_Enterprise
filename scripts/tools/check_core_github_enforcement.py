#!/usr/bin/env python3
"""Verify GitHub-side enforcement artifacts for Host Shell core protection (P2A).

Repository JSON approvals alone are insufficient. This check fails closed unless:
  1. ``.github/CODEOWNERS`` exists and covers core protection machinery paths
  2. Tool Protection workflow still invokes ``check_core_protection.py``
  3. Required-check documentation is present for branch protection operators

Does **not** call the GitHub API (no tokens required). Operators must still
enable branch protection: required status checks + required CODEOWNERS reviews.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
WORKFLOW = ROOT / ".github" / "workflows" / "tool-protection.yml"
DOCS = ROOT / "docs" / "PLUGIN_WORKER_P2A.md"

REQUIRED_OWNER_PATHS = (
    "/tools/core_protection.json",
    "/scripts/tools/check_core_protection.py",
    "/.github/workflows/tool-protection.yml",
    "/tools/core_releases/",
)

REQUIRED_DOC_NEEDLES = (
    "CODEOWNERS",
    "required status checks",
    "branch protection",
    "CORE_RELEASE_APPROVAL",
)


def main() -> int:
    errors: list[str] = []

    if not CODEOWNERS.is_file():
        errors.append("missing .github/CODEOWNERS")
    else:
        text = CODEOWNERS.read_text(encoding="utf-8")
        for path in REQUIRED_OWNER_PATHS:
            if path not in text:
                errors.append(f"CODEOWNERS missing coverage for {path}")

    if not WORKFLOW.is_file():
        errors.append("missing tool-protection.yml")
    else:
        wf = WORKFLOW.read_text(encoding="utf-8")
        if "check_core_protection.py" not in wf:
            errors.append("tool-protection.yml does not invoke check_core_protection.py")
        if "CORE_RELEASE_APPROVAL" not in wf:
            errors.append("tool-protection.yml missing CORE_RELEASE_APPROVAL wiring")

    if not DOCS.is_file():
        errors.append("missing docs/PLUGIN_WORKER_P2A.md (branch protection operator guide)")
    else:
        docs = DOCS.read_text(encoding="utf-8")
        docs_l = docs.lower()
        for needle in REQUIRED_DOC_NEEDLES:
            if needle.lower() not in docs_l:
                errors.append(f"docs missing required guidance: {needle}")

    if errors:
        print("CORE GITHUB ENFORCEMENT FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nCore approval must be enforced via CODEOWNERS + required GitHub "
            "checks/reviews, not repository JSON alone.",
            file=sys.stderr,
        )
        return 1

    print(
        "CORE GITHUB ENFORCEMENT OK "
        "(CODEOWNERS + workflow wiring + operator docs present; "
        "enable branch protection on the locked baseline)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
