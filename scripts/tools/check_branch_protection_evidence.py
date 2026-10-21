#!/usr/bin/env python3
"""Report GitHub branch-protection / CODEOWNERS enforcement evidence (P2A.1).

Uses authorized ``gh`` API when available. If access is unavailable, prints
``UNKNOWN`` (never false PASS). Does not claim production deploy.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "techadv50-boop/EarthVision_Enterprise"
BRANCHES = (
    "cursor/scene-download-eye-5d6d",
    "cursor/sateye-plugin-manager-p1-5d6d",
    "cursor/sateye-plugin-worker-p2a-5d6d",
)


def gh_json(args: list[str]) -> tuple[str, dict | list | None]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return "UNKNOWN", {"error": str(exc)}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        # Common: 404 not found / not admin / SSO
        return "UNKNOWN", {"error": err or f"gh exit {proc.returncode}"}
    try:
        return "OK", json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "UNKNOWN", {"error": "invalid JSON from gh", "raw": proc.stdout[:500]}


def main() -> int:
    codeowners = ROOT / ".github" / "CODEOWNERS"
    local = {
        "codeowners_present": codeowners.is_file(),
        "codeowners_covers_core": False,
    }
    if codeowners.is_file():
        text = codeowners.read_text(encoding="utf-8")
        local["codeowners_covers_core"] = all(
            p in text
            for p in (
                "/tools/core_protection.json",
                "/scripts/tools/check_core_protection.py",
                "/.github/workflows/tool-protection.yml",
            )
        )

    results: dict = {
        "schema_version": 1,
        "repo": REPO,
        "local_codeowners": local,
        "branches": {},
        "overall": "UNKNOWN",
    }

    any_pass = False
    any_unknown = False
    for branch in BRANCHES:
        status, payload = gh_json(
            [
                "api",
                f"repos/{REPO}/branches/{branch}/protection",
                "-H",
                "Accept: application/vnd.github+json",
            ]
        )
        entry: dict = {"api_status": status, "protection": payload}
        if status == "OK" and isinstance(payload, dict):
            checks = (
                (payload.get("required_status_checks") or {}).get("contexts")
                or (payload.get("required_status_checks") or {}).get("checks")
                or []
            )
            reviews = payload.get("required_pull_request_reviews") or {}
            entry["required_status_checks"] = checks
            entry["require_codeowner_reviews"] = bool(
                reviews.get("require_code_owner_reviews")
            )
            # PASS only if code owner reviews required AND some status checks exist
            if entry["require_codeowner_reviews"] and checks:
                entry["verdict"] = "PASS"
                any_pass = True
            else:
                entry["verdict"] = "FAIL"
        else:
            entry["verdict"] = "UNKNOWN"
            any_unknown = True
        results["branches"][branch] = entry

    if any_pass and not any_unknown:
        # Only claim PASS when every checked branch returned API OK with requirements
        if all(v.get("verdict") == "PASS" for v in results["branches"].values()):
            results["overall"] = "PASS"
        else:
            results["overall"] = "UNKNOWN"
    else:
        results["overall"] = "UNKNOWN"

    print(json.dumps(results, indent=2))
    # Exit 0 even on UNKNOWN — evidence report, not a hard CI gate failure
    # (operator must enable protection). Local CODEOWNERS still enforced elsewhere.
    if not local["codeowners_present"] or not local["codeowners_covers_core"]:
        print("LOCAL CODEOWNERS incomplete", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
