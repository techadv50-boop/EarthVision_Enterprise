#!/usr/bin/env bash
# Fail-closed CI / Tool Protection gate for Deploy SATEYE.
#
# Verifies that required GitHub Actions workflows completed successfully for the
# EXACT commit SHA about to be deployed. Missing, pending, failed, cancelled,
# skipped, or wrong-SHA results abort the deploy.
#
# Env:
#   DEPLOY_CI_GATE_SHA          (required) full 40-char SHA
#   DEPLOY_CI_GATE_REPO         default techadv50-boop/EarthVision_Enterprise
#   DEPLOY_CI_GATE_WORKFLOWS    default ci.yml,tool-protection.yml
#   DEPLOY_CI_GATE_FIXTURE      optional JSON fixture (tests / offline)
#
# workflow_dispatch cannot bypass this gate — the Deploy workflow must invoke it.
set -euo pipefail

REPO="${DEPLOY_CI_GATE_REPO:-techadv50-boop/EarthVision_Enterprise}"
SHA="${DEPLOY_CI_GATE_SHA:-}"
REQUIRED_WORKFLOWS="${DEPLOY_CI_GATE_WORKFLOWS:-ci.yml,tool-protection.yml}"
FIXTURE="${DEPLOY_CI_GATE_FIXTURE:-}"

die() { printf '[ci-gate] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[ci-gate] %s\n' "$*"; }

[[ -n "$SHA" ]] || die "DEPLOY_CI_GATE_SHA is required"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "DEPLOY_CI_GATE_SHA must be a full 40-char commit SHA (got: $SHA)"

export DEPLOY_CI_GATE_WORKFLOWS="$REQUIRED_WORKFLOWS"
export DEPLOY_CI_GATE_SHA="$SHA"

fetch_runs_json() {
  if [[ -n "$FIXTURE" ]]; then
    [[ -f "$FIXTURE" ]] || die "fixture missing: $FIXTURE"
    cat "$FIXTURE"
    return 0
  fi
  command -v gh >/dev/null 2>&1 || die "gh CLI required for live CI gate"
  gh api \
    -H "Accept: application/vnd.github+json" \
    "/repos/${REPO}/actions/runs?head_sha=${SHA}&per_page=100" \
    --jq '{sha: "'"$SHA"'", workflow_runs: [.workflow_runs[] | {id, name, path, head_sha, status, conclusion, event}]}'
}

log "verifying CI gate for sha=$SHA workflows=$REQUIRED_WORKFLOWS"
_JSON_TMP="$(mktemp)"
trap 'rm -f "$_JSON_TMP"' EXIT
fetch_runs_json >"$_JSON_TMP"
python3 - "$_JSON_TMP" <<'PY'
import json, os, sys

path = sys.argv[1]
sha = os.environ["DEPLOY_CI_GATE_SHA"]
want = [w.strip() for w in os.environ.get("DEPLOY_CI_GATE_WORKFLOWS", "").split(",") if w.strip()]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
runs = data.get("workflow_runs") or []

fixture_sha = data.get("sha") or data.get("expected_sha")
if fixture_sha and fixture_sha != sha:
    print(f"ERROR: fixture/API sha {fixture_sha} != deploy sha {sha}", file=sys.stderr)
    sys.exit(2)

latest = {}
for r in runs:
    path = (r.get("path") or "").replace("\\", "/")
    if "/" in path:
        path = path.split("/")[-1]
    if not path:
        name = (r.get("name") or "").lower()
        if "tool protection" in name or name == "tool-protection":
            path = "tool-protection.yml"
        elif name == "ci" or name.startswith("ci"):
            path = "ci.yml"
        else:
            continue
    head = r.get("head_sha") or ""
    if head and head != sha:
        print(
            f"ERROR: run id={r.get('id')} path={path} head_sha={head} != deploy sha {sha}",
            file=sys.stderr,
        )
        sys.exit(3)
    prev = latest.get(path)
    if prev is None or int(r.get("id") or 0) > int(prev.get("id") or 0):
        latest[path] = {**r, "path": path}

ok = True
for w in want:
    r = latest.get(w)
    if r is None:
        print(f"FAIL: missing workflow run for {w} on {sha}", file=sys.stderr)
        ok = False
        continue
    status = (r.get("status") or "").lower()
    conclusion = (r.get("conclusion") or "").lower() if r.get("conclusion") is not None else ""
    print(f"check {w}: status={status} conclusion={conclusion} id={r.get('id')}")
    if status != "completed":
        print(f"FAIL: {w} not completed (status={status})", file=sys.stderr)
        ok = False
        continue
    if conclusion != "success":
        # failed, cancelled, skipped, timed_out, action_required, neutral, stale, ...
        print(f"FAIL: {w} conclusion={conclusion!r} (require success)", file=sys.stderr)
        ok = False
        continue

if not ok:
    sys.exit(1)
print(f"OK: all required workflows succeeded for {sha}")
PY
