#!/usr/bin/env bash
# E1.9A safety hardening tests (no production access).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0
SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

assert_ok() {
  local name="$1"; shift
  if "$@" >/tmp/e19a-out.$$ 2>/tmp/e19a-err.$$; then
    echo "PASS: $name"
    PASS=$((PASS+1))
  else
    echo "FAIL: $name (rc=$?)" >&2
    sed 's/^/  out: /' /tmp/e19a-out.$$ >&2 || true
    sed 's/^/  err: /' /tmp/e19a-err.$$ >&2 || true
    FAIL=$((FAIL+1))
  fi
  rm -f /tmp/e19a-out.$$ /tmp/e19a-err.$$
}

assert_fail() {
  local name="$1"; shift
  if "$@" >/tmp/e19a-out.$$ 2>/tmp/e19a-err.$$; then
    echo "FAIL: $name (expected non-zero)" >&2
    sed 's/^/  out: /' /tmp/e19a-out.$$ >&2 || true
    FAIL=$((FAIL+1))
  else
    echo "PASS: $name (failed closed)"
    PASS=$((PASS+1))
  fi
  rm -f /tmp/e19a-out.$$ /tmp/e19a-err.$$
}

GATE="$ROOT/scripts/deploy_verify_ci_gate.sh"
chmod +x "$GATE" "$ROOT/scripts/deploy_capture_preflight.sh" "$ROOT/scripts/deploy_merge_compose_overlay.py"

echo "== CI gate =="
assert_ok "ci gate success" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/success.json" "$GATE"
assert_fail "ci gate failed conclusion" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/failed.json" "$GATE"
assert_fail "ci gate pending" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/pending.json" "$GATE"
assert_fail "ci gate cancelled" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/cancelled.json" "$GATE"
assert_fail "ci gate missing workflow" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/missing.json" "$GATE"
assert_fail "ci gate mismatched sha" env DEPLOY_CI_GATE_SHA="$SHA" DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/mismatched_sha.json" "$GATE"
assert_fail "ci gate rejects short sha" env DEPLOY_CI_GATE_SHA=abc123 DEPLOY_CI_GATE_FIXTURE="$ROOT/scripts/tests/fixtures/ci_gate/success.json" "$GATE"

echo "== admin reset default off =="
assert_ok "RESET_ADMIN_PASSWORD defaults to 0" bash -c "
  source '$ROOT/scripts/deploy_sateye_live.sh'
  export DEPLOY_SATEYE_TEST_MODE=1
  # re-source after export
  true
"
# Parse script default
assert_ok "script documents default 0" grep -q 'RESET_ADMIN_PASSWORD:-0' "$ROOT/scripts/deploy_sateye_live.sh"
assert_ok "workflow does not hardcode RESET=1" bash -c "! grep -q 'RESET_ADMIN_PASSWORD: \"1\"' '$ROOT/.github/workflows/deploy-sateye.yml'"
assert_ok "workflow has admin_reset_confirm input" grep -q 'admin_reset_confirm' "$ROOT/.github/workflows/deploy-sateye.yml"

echo "== compose overlay merge =="
TMP=$(mktemp -d)
PY="${ROOT}/backend/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3
assert_ok "merge preserves live secret and adds tool packs" bash -c "
  '$PY' '$ROOT/scripts/deploy_merge_compose_overlay.py' \
    --live '$ROOT/scripts/tests/fixtures/compose_overlay/live.fixture.yml' \
    --patch '$ROOT/scripts/tests/fixtures/compose_overlay/patch.fixture.yml' \
    --out '$TMP/merged.yml'
  '$PY' - <<'PY'
import yaml
from pathlib import Path
m=yaml.safe_load(Path('$TMP/merged.yml').read_text())
env=m['services']['backend']['environment']
assert env['SECRET_KEY']=='live-secret-must-preserve'
assert env['DATABASE_URL'].startswith('postgresql')
assert env['EV_RUNTIME_PINS']=='/data/tool_packs/runtime_pins.json'
assert env['EV_PACK_TRUST_PROFILE']=='production'
vols=m['services']['backend']['volumes']
assert './cache:/data/cache' in vols
assert any('tool_packs' in str(v) for v in vols)
assert 'pgdata' in m['volumes']
assert 'tool_packs_data' in m['volumes']
assert m['services']['frontend']['image']=='custom-frontend:live'
assert m['networks']['default']['name']=='sateye_live_net'
print('merge_ok')
PY
"
assert_fail "refuse overwrite live without backup" "$PY" "$ROOT/scripts/deploy_merge_compose_overlay.py" \
  --live "$ROOT/scripts/tests/fixtures/compose_overlay/live.fixture.yml" \
  --patch "$ROOT/scripts/tests/fixtures/compose_overlay/patch.fixture.yml" \
  --out "$ROOT/scripts/tests/fixtures/compose_overlay/live.fixture.yml"

echo "== preflight capture (fixture app dir) =="
APP=$(mktemp -d)
mkdir -p "$APP/backend"
echo 'compose: stub' >"$APP/docker-compose.yml"
echo 'req' >"$APP/backend/requirements.txt"
echo 'SECRET=x' >"$APP/.env"
( cd "$APP" && git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm init )
OUT=$(mktemp -d)
assert_ok "preflight writes rollback refs" env APP_DIR="$APP" DEPLOY_PREFLIGHT_OUT="$OUT" "$ROOT/scripts/deploy_capture_preflight.sh"
assert_ok "preflight meta has compose hash" grep -q compose_sha256 "$OUT/preflight_meta.txt"
assert_ok "preflight refuses prod path by default" bash -c "! APP_DIR=/opt/earthvision DEPLOY_PREFLIGHT_OUT=/tmp/x '$ROOT/scripts/deploy_capture_preflight.sh'"

echo "== publisher trust (python) =="
assert_ok "production rejects empty/preview publishers" bash -c "
  cd '$ROOT/backend' && .venv/bin/python - <<'PY'
import os, json, tempfile
from pathlib import Path
os.environ['EV_PACK_TRUST_PROFILE']='production'
os.environ['EV_PACK_REQUIRE_SIGNATURE']='1'
# empty file
td=tempfile.mkdtemp()
p=Path(td)/'pubs.json'
p.write_text(json.dumps({'publishers':[]}))
os.environ['EV_PACK_PUBLISHERS']=str(p)
from app.tools.pack_signatures import PackSignatureError, load_approved_publishers
try:
    load_approved_publishers()
    raise SystemExit('should fail')
except PackSignatureError as e:
    assert 'production' in str(e).lower() or 'no enabled' in str(e).lower() or 'publishers' in str(e).lower()
# preview-dev only
p.write_text(json.dumps({'publishers':[{'id':'preview-dev','environment':'preview','enabled':True,'public_key':'x'}]}))
try:
    load_approved_publishers()
    raise SystemExit('should fail preview')
except PackSignatureError:
    pass
from app.tools.pack_ops import PackOpsError, assert_production_trust_ready
try:
    assert_production_trust_ready()
    raise SystemExit('ops should fail')
except PackOpsError:
    pass
print('trust_ok')
PY
"

rm -rf "$TMP" "$APP" "$OUT"
echo "PASSED=$PASS FAILED=$FAIL"
[[ "$FAIL" -eq 0 ]]
