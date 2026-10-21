#!/usr/bin/env bash
# E1.7 isolated preview validation on THIS machine only.
# Refuses production project names / compose files / /opt/earthvision.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.preview.yml}"
PROJECT="${COMPOSE_PROJECT_NAME:-sateye-preview}"
ENV_FILE="${ENV_FILE:-.env.preview}"
EVIDENCE="${EVIDENCE_DIR:-/tmp/e17_preview_evidence}"
mkdir -p "$EVIDENCE"

die() { echo "ERROR: $*" >&2; exit 1; }

echo "=== E1.7 preview isolation preflight ==="
[[ "$(hostname)" != "zhzh" ]] || die "refusing to run on production hostname zhzh"
[[ ! -d /opt/earthvision ]] || die "refusing: /opt/earthvision present (looks like live host)"
case "$PROJECT" in
  sateye-fz2ic4|earthvision|sateye-prod|prod) die "refusing production-like project: $PROJECT" ;;
esac
case "$COMPOSE_FILE" in
  docker-compose.yml|docker-compose.prod.yml) die "refusing production compose: $COMPOSE_FILE" ;;
esac
command -v docker >/dev/null || die "docker required"
docker info >/dev/null 2>&1 || die "docker daemon not reachable"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.preview.example "$ENV_FILE"
  echo "created $ENV_FILE from example"
fi

echo "project=$PROJECT file=$COMPOSE_FILE"
echo "isolation_ok=1" | tee "$EVIDENCE/isolation.txt"

echo "=== Build & start preview stack ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo "=== Wait for health ==="
for i in $(seq 1 40); do
  if curl -fsS --max-time 5 "http://127.0.0.1:8202/health" >/dev/null 2>&1; then
    echo "health_ok attempt=$i"
    break
  fi
  sleep 3
  [[ "$i" -eq 40 ]] && die "preview health failed"
done
curl -fsS "http://127.0.0.1:8202/health" | tee "$EVIDENCE/health.json"
curl -fsS -o /dev/null -w "homepage_http=%{http_code}\n" "http://127.0.0.1:8202/" | tee "$EVIDENCE/homepage.txt"

echo "=== Record Host Shell image digests (BEFORE pack ops) ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q backend frontend | while read -r id; do
  docker image inspect "$id" --format '{{.Id}} {{.RepoTags}}'
done | tee "$EVIDENCE/images_before.txt"
BEFORE_BACKEND="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q backend | head -1)"
BEFORE_FRONTEND="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q frontend | head -1)"
docker image inspect "$BEFORE_BACKEND" --format '{{.Id}}' | tee "$EVIDENCE/backend_before.id"
docker image inspect "$BEFORE_FRONTEND" --format '{{.Id}}' | tee "$EVIDENCE/frontend_before.id"

echo "=== Bootstrap builtin pins + install packs inside backend (no rebuild) ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python -c "from app.tools.pack_ops import ensure_default_pins; print(ensure_default_pins())"

# Install 1.0.0 and 1.1.0 from read-only seed (separate from activation)
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python - <<'PY' | tee "$EVIDENCE/install_1_0_0.json"
import json, sys
sys.path.insert(0, "/app")
from pathlib import Path
from app.tools.pack_ops import install_pack_from_dir
r = install_pack_from_dir(Path("/seed/artifacts/true_color/1.0.0"), tool_id="true_color", version="1.0.0", actor="e17-preview", confirm="install")
print(json.dumps(r))
PY

docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python - <<'PY' | tee "$EVIDENCE/install_1_1_0.json"
import json, sys
from pathlib import Path
from app.tools.pack_ops import install_pack_from_dir
r = install_pack_from_dir(Path("/seed/artifacts/true_color/1.1.0"), tool_id="true_color", version="1.1.0", actor="e17-preview", confirm="install")
print(json.dumps(r))
PY

echo "=== Confirm still builtin before activate ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python -c "from app.tools.runtime_pins import get_pin; import json; print(json.dumps(get_pin('true_color')))" \
  | tee "$EVIDENCE/pin_before_activate.json"

echo "=== Activate 1.0.0 then 1.1.0; rollback; concurrent render churn ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python - <<'PY' | tee "$EVIDENCE/activate_rollback.json"
import json, base64, concurrent.futures
from app.tools.pack_ops import activate_pack, rollback_pack
from app.tools.runtime_pins import get_pin
from app.schemas.composite import CompositeRequest
from app.services.composite_service import CompositeService
import numpy as np

activate_pack(tool_id="true_color", version="1.0.0", actor="e17-preview", confirm="activate")
assert get_pin("true_color")["version"] == "1.0.0"
activate_pack(tool_id="true_color", version="1.1.0", actor="e17-preview", confirm="activate")
assert get_pin("true_color")["version"] == "1.1.0"

rgb = np.full((8, 8, 3), 90.0)
mask = np.ones((8, 8), dtype=bool)
bounds = [1.0, 2.0, 3.0, 4.0]
CompositeService._load_visual_rgb = lambda self, scene_id, bbox, size: (rgb, bounds, mask, None)
req = CompositeRequest(preset="true_color", scene_id="e17", size=64)

def one(i):
    if i == 5:
        rollback_pack(tool_id="true_color", to="1.0.0", actor="e17-preview", confirm="rollback")
    if i == 10:
        rollback_pack(tool_id="true_color", to="builtin", actor="e17-preview", confirm="rollback")
    resp = CompositeService().render_composite(req)
    raw = base64.b64decode(resp.overlay_base64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return (resp.message or "")[:80]

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    msgs = list(pool.map(one, range(16)))

# Leave on 1.1.0 for persistence check
activate_pack(tool_id="true_color", version="1.1.0", actor="e17-preview", confirm="activate")
print(json.dumps({"pin": get_pin("true_color"), "sample_messages": msgs[:4], "n": len(msgs)}))
PY

echo "=== Reject unsigned install ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python - <<'PY' | tee "$EVIDENCE/reject_unsigned.txt" || true
import tempfile, shutil
from pathlib import Path
from app.tools.pack_ops import PackOpsError, install_pack_from_dir
src = Path("/seed/artifacts/true_color/1.0.0")
td = Path(tempfile.mkdtemp())
shutil.copytree(src, td / "p")
(td / "p" / "SIGNATURE.json").unlink(missing_ok=True)
try:
    install_pack_from_dir(td / "p", tool_id="true_color", version="9.9.9", actor="e17", confirm="install")
    raise SystemExit("FAIL: unsigned accepted")
except PackOpsError as e:
    print("REJECTED_OK", e)
PY

echo "=== Image digests AFTER pack ops (must match before) ==="
AFTER_BACKEND="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q backend | head -1)"
AFTER_FRONTEND="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q frontend | head -1)"
docker image inspect "$AFTER_BACKEND" --format '{{.Id}}' | tee "$EVIDENCE/backend_after.id"
docker image inspect "$AFTER_FRONTEND" --format '{{.Id}}' | tee "$EVIDENCE/frontend_after.id"
diff -u "$EVIDENCE/backend_before.id" "$EVIDENCE/backend_after.id"
diff -u "$EVIDENCE/frontend_before.id" "$EVIDENCE/frontend_after.id"
echo "image_digests_unchanged=1" | tee "$EVIDENCE/image_digest_check.txt"

echo "=== Restart backend; pins + artifacts persist ==="
# Always pass --env-file so POSTGRES password matches the volume (compose defaults differ).
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --force-recreate --no-deps backend
sleep 8
for i in $(seq 1 30); do
  curl -fsS --max-time 5 "http://127.0.0.1:8200/health" >/dev/null 2>&1 && break
  sleep 2
done
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python -c "from app.tools.runtime_pins import get_pin; from pathlib import Path; import json; p=get_pin('true_color'); assert p.get('version')=='1.1.0', p; assert Path('/data/tool_packs/artifacts/true_color/1.0.0/pack.json').is_file(); assert Path('/data/tool_packs/artifacts/true_color/1.1.0/pack.json').is_file(); print(json.dumps({'persisted_pin': p, 'ok': True}))" \
  | tee "$EVIDENCE/persist_after_restart.json"

echo "=== Catalog / canary smoke inside container ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" exec -T backend \
  python - <<'PY' | tee "$EVIDENCE/tools_canary.json"
import json
from app.services.detection_service import TASK_META
from app.services.optical_ship_detection import OPTICAL_SHIP_TASKS
from app.tools.manifest_loader import load_manifest
m = load_manifest()
counts = m.get("counts") or {}
print(json.dumps({
  "manifest_unique": counts.get("unique_ids"),
  "catalog_entries": counts.get("catalog_entries"),
  "ship_in_task_meta": "ship_detection" in TASK_META,
  "ship_optical": "ship_detection" in OPTICAL_SHIP_TASKS,
}))
PY

echo "=== DONE — evidence in $EVIDENCE ==="
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps | tee "$EVIDENCE/compose_ps.txt"
