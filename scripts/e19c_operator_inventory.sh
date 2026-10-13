#!/usr/bin/env bash
# Stage E1.9C — Read-only production inventory helper for an authorized operator.
#
# Writes ONLY under OUT_DIR (must be outside APP_DIR).
# Does NOT modify Git, compose, containers, volumes, networks, credentials, or databases.
# Does NOT trigger Deploy SATEYE or any workflow_dispatch.
#
# Usage:
#   OUT_DIR=/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ) \
#   APP_DIR=/opt/earthvision \
#   bash scripts/e19c_operator_inventory.sh
#
# Optional:
#   EXPECTED_HOST=zhzh
#   EXPECTED_PROJECT=sateye-fz2ic4
#   SKIP_HOST_CHECK=1          # emergency only — not recommended
#   INCLUDE_RUNNER_CHECKS=1    # default 1
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/earthvision}"
OUT_DIR="${OUT_DIR:-}"
EXPECTED_HOST="${EXPECTED_HOST:-zhzh}"
EXPECTED_PROJECT="${EXPECTED_PROJECT:-sateye-fz2ic4}"
EXPECTED_BASELINE="${EXPECTED_BASELINE:-1e71b7abaa0fa8d4b70225d949afc8ae79923bb6}"
APPROVED_TIP="${APPROVED_TIP:-e3012ce0a26e049d0af981d5994d0d829c3b647e}"
INCLUDE_RUNNER_CHECKS="${INCLUDE_RUNNER_CHECKS:-1}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

die() { printf '[e19c] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[e19c] %s\n' "$*"; }
stop() { printf '%s\n' "$*" | tee "$OUT_DIR/STOP.txt" >&2; exit 2; }

[[ -n "$OUT_DIR" ]] || die "OUT_DIR is required (use a path under /tmp, outside APP_DIR)"
[[ "$OUT_DIR" == /* ]] || die "OUT_DIR must be absolute"
case "$OUT_DIR" in
  "$APP_DIR"|"$APP_DIR"/*) die "OUT_DIR must not be inside APP_DIR ($APP_DIR)" ;;
esac

mkdir -p "$OUT_DIR"
log "OUT_DIR=$OUT_DIR"

# --- Identity ---
{
  echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname 2>/dev/null || true)"
  echo "whoami=$(whoami 2>/dev/null || true)"
  echo "app_dir=$APP_DIR"
  echo "app_dir_exists=$([[ -d $APP_DIR ]] && echo 1 || echo 0)"
  echo "expected_host=$EXPECTED_HOST"
  echo "expected_project=$EXPECTED_PROJECT"
  echo "approved_tip=$APPROVED_TIP"
  echo "expected_baseline=$EXPECTED_BASELINE"
} | tee "$OUT_DIR/01_identity.txt"

if [[ "${SKIP_HOST_CHECK:-0}" != "1" ]]; then
  [[ "$(hostname)" == "$EXPECTED_HOST" ]] || stop "STOP: hostname $(hostname) != expected $EXPECTED_HOST"
  [[ -d "$APP_DIR" ]] || stop "STOP: APP_DIR missing: $APP_DIR"
else
  log "WARNING: SKIP_HOST_CHECK=1 — identity STOP disabled"
fi

cd "$APP_DIR"

# --- Compose project / services ---
{
  echo "=== docker compose ls ==="
  docker compose ls 2>/dev/null || true
  echo "=== container labels ==="
  docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}\t{{.Status}}\t{{.Image}}' 2>/dev/null || true
  echo "=== detected projects ==="
  docker ps --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | grep -v '^$' | sort -u || true
} | tee "$OUT_DIR/02_compose_project.txt"

PROJECTS="$(docker ps --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | grep -v '^$' | sort -u || true)"
if [[ "${SKIP_HOST_CHECK:-0}" != "1" ]]; then
  if [[ -n "$PROJECTS" ]] && ! grep -qx "$EXPECTED_PROJECT" <<<"$PROJECTS"; then
    if ! grep -q "$EXPECTED_PROJECT" <<<"$PROJECTS"; then
      stop "STOP: compose project(s) [$PROJECTS] do not include expected $EXPECTED_PROJECT"
    fi
  fi
fi

{
  echo "=== docker compose ps ==="
  docker compose ps 2>/dev/null || true
  echo "=== services ==="
  docker compose config --services 2>/dev/null || true
} | tee "$OUT_DIR/03_services.txt"

# --- Git ---
{
  if [[ -d .git ]]; then
    echo "branch=$(git branch --show-current 2>/dev/null || true)"
    echo "commit=$(git rev-parse HEAD 2>/dev/null || true)"
    echo "commit_short=$(git rev-parse --short HEAD 2>/dev/null || true)"
    echo "status_summary=$(git status -sb 2>/dev/null | head -1 || true)"
    echo "dirty_paths=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    if git cat-file -e "${EXPECTED_BASELINE}^{commit}" 2>/dev/null; then
      if git merge-base --is-ancestor "$EXPECTED_BASELINE" HEAD 2>/dev/null; then
        echo "baseline_1e71b7a_ancestor=yes"
      else
        echo "baseline_1e71b7a_ancestor=no"
      fi
    else
      echo "baseline_1e71b7a_object=missing_locally"
    fi
    if [[ "$(git rev-parse HEAD 2>/dev/null || echo none)" == "$APPROVED_TIP" ]]; then
      echo "live_equals_approved_tip_e3012ce=yes"
    else
      echo "live_equals_approved_tip_e3012ce=no"
    fi
    echo "baseline_tag=$(git tag -l 'sateye-baseline-20261012-1e71b7a' 2>/dev/null || true)"
  else
    echo "git=MISSING"
  fi
} | tee "$OUT_DIR/04_git.txt"

{
  if [[ -f .env ]]; then
    echo "env_present=1"
    echo "env_size=$(wc -c < .env | tr -d ' ')"
    echo "env_sha256=$(sha256sum .env | awk '{print $1}')"
  else
    echo "env_present=0"
  fi
  if [[ -f "$COMPOSE_FILE" ]]; then
    echo "compose_file=$COMPOSE_FILE"
    echo "compose_sha256=$(sha256sum "$COMPOSE_FILE" | awk '{print $1}')"
  else
    echo "compose_file=MISSING"
  fi
  if [[ -f backend/requirements.txt ]]; then
    echo "requirements_sha256=$(sha256sum backend/requirements.txt | awk '{print $1}')"
  fi
} | tee "$OUT_DIR/05_fingerprints.txt"

# --- Images ---
{
  echo "=== docker compose images ==="
  docker compose images 2>/dev/null || true
  echo "=== service inspect ==="
  for svc in backend frontend; do
    id="$(docker compose images -q "$svc" 2>/dev/null | head -1 || true)"
    if [[ -n "${id:-}" ]]; then
      docker image inspect "$id" --format "$svc Id={{.Id}} RepoDigests={{json .RepoDigests}} RepoTags={{json .RepoTags}} Created={{.Created}} Size={{.Size}}" 2>/dev/null || true
    else
      echo "$svc Id=MISSING"
    fi
  done
  echo "=== docker images --digests (first 80) ==="
  docker images --digests --format '{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Digest}}\t{{.CreatedSince}}' 2>/dev/null | head -80 || true
} | tee "$OUT_DIR/06_images.txt"

{
  PRESERVE="${PRESERVE_DIR:-/home/zh/earthvision-deploy-preserve}"
  echo "preserve_dir=$PRESERVE"
  if [[ -d "$PRESERVE" ]]; then
    echo "preserve_dir_present=1"
    ls -la "$PRESERVE" 2>/dev/null | head -50 || true
  else
    echo "preserve_dir_present=0"
  fi
  echo "PRIOR_GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
  echo "NOTE=Record backend/frontend Id+RepoDigests from 06_images.txt as rollback priors."
} | tee "$OUT_DIR/07_rollback.txt"

# --- Redacted compose ---
docker compose config --services 2>/dev/null | tee "$OUT_DIR/08_compose_services.txt" || true

python3 - "$OUT_DIR/09_compose_redacted.yml" <<'PY'
import re, subprocess, sys
out = sys.argv[1]
SENSITIVE = re.compile(
    r"(PASSWORD|SECRET|TOKEN|PRIVATE|API[_-]?KEY|AUTH|CREDENTIAL|DATABASE_URL|"
    r"POSTGRES|REDIS_URL|CONNECTION|ADMIN_PASS|JWT|SESSION|SMTP|AWS_|GCP_|GOOGLE_|"
    r"PRIVATE_KEY|PUBLISHER.*KEY)",
    re.I,
)
CONN = re.compile(r"(?i)\b(postgres|postgresql|redis|mysql|mongodb)://\S+")

def redact_line(line: str) -> str:
    m = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*[=:]\s*)(.*)$", line)
    if m:
        indent, key, sep, val = m.groups()
        if SENSITIVE.search(key) or CONN.search(val) or re.search(r"(?i)(password|secret|token)", val):
            return f"{indent}{key}{sep}<redacted>\n"
        stripped = val.strip().strip("\"'")
        if len(stripped) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_\-]{40,}", stripped):
            return f"{indent}{key}{sep}<redacted>\n"
    return CONN.sub(r"\1://<redacted>", line)

try:
    raw = subprocess.check_output(["docker", "compose", "config"], stderr=subprocess.STDOUT, text=True)
except Exception as exc:
    open(out, "w", encoding="utf-8").write(f"# compose_config_error: {exc}\n")
    sys.exit(0)
with open(out, "w", encoding="utf-8") as f:
    for line in raw.splitlines(True):
        f.write(redact_line(line))
print(f"wrote {out}")
PY

{
  echo "=== volume names ==="
  docker volume ls --format '{{.Name}}\t{{.Driver}}' 2>/dev/null || true
  echo "=== mounts ==="
  for cid in $(docker compose ps -q 2>/dev/null); do
    docker inspect "$cid" --format '{{.Name}} {{range .Mounts}}[{{.Type}} name={{.Name}} src={{.Source}} dst={{.Destination}}] {{end}}' 2>/dev/null || true
  done
} | tee "$OUT_DIR/10_volumes_mounts.txt"

# --- Health ---
{
  echo "=== compose ps ==="
  docker compose ps 2>/dev/null || true
  for url in \
    http://127.0.0.1:8080/health \
    http://127.0.0.1:8000/health \
    http://127.0.0.1:8100/health \
    http://127.0.0.1:8101/health \
    https://sateye.xdgen.com/health
  do
    code=$(curl -sS -m 8 -o /tmp/e19c_hbody.txt -w '%{http_code}' "$url" 2>/dev/null || echo ERR)
    echo -n "$url http=$code "
    python3 - <<'PY'
import json
try:
    d=json.load(open("/tmp/e19c_hbody.txt"))
    print({k:d.get(k) for k in ("status","version","environment","database") if k in d})
except Exception:
    print("(non-json)")
PY
  done
} | tee "$OUT_DIR/11_health.txt"

{
  echo "=== backend env NAMES only ==="
  cid=$(docker compose ps -q backend 2>/dev/null | head -1 || true)
  if [[ -n "${cid:-}" ]]; then
    docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | sed -E 's/^([^=]+)=.*/\1=<redacted>/' | sort
    echo "=== EV_* trust-related names ==="
    docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | sed -E 's/=.*//' | egrep '^(EV_PACK_|EV_TOOL_|EV_RUNTIME_|EV_ARTIFACTS_)' \
      || echo "no_EV_PACK_env_names"
  else
    echo "backend_container=MISSING"
  fi
} | tee "$OUT_DIR/12_env_names.txt"

# --- Baseline / config probes ---
{
  echo "commit=$(git rev-parse HEAD 2>/dev/null || true)"
  if git cat-file -e "${EXPECTED_BASELINE}^{commit}" 2>/dev/null; then
    git merge-base --is-ancestor "$EXPECTED_BASELINE" HEAD 2>/dev/null \
      && echo baseline_ancestor=yes || echo baseline_ancestor=no
  else
    echo baseline_ancestor=object_missing
  fi
  for p in backend/app/services frontend/src docker-compose.yml; do
    [[ -e "$p" ]] && echo "path_present=$p" || echo "path_missing=$p"
  done
  for pair in \
    "local_tools_runtime:http://127.0.0.1:8000/api/v1/tools/runtime" \
    "public_tools_runtime:https://sateye.xdgen.com/api/v1/tools/runtime" \
    "public_composites:https://sateye.xdgen.com/api/v1/analytics/composites"
  do
    name="${pair%%:*}"
    url="${pair#*:}"
    code=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo ERR)
    echo "${name}_http=$code"
  done
} | tee "$OUT_DIR/14_baseline_and_config.txt"

# --- Runner (optional) ---
if [[ "$INCLUDE_RUNNER_CHECKS" == "1" ]]; then
  {
    echo "hostname=$(hostname)"
    echo "=== runner-like processes ==="
    ps aux 2>/dev/null | egrep -i 'actions\.runner|Runner\.Listener|sateye-live' | grep -v egrep \
      | awk '{print $1,$2,$11,$12,$13,$14,$15}' | head -20 || true
    systemctl list-units --type=service --all 2>/dev/null | egrep -i 'actions.runner|github' | head -20 || true
    if command -v gh >/dev/null 2>&1; then
      echo "=== gh auth status (scrubbed) ==="
      gh auth status 2>&1 | sed -E 's/[A-Za-z0-9_]{20,}/<redacted>/g' || true
      echo "=== runners API ==="
      gh api repos/techadv50-boop/EarthVision_Enterprise/actions/runners \
        --jq '.runners[]? | {name,id,status,busy,labels:[.labels[].name]}' 2>&1 || echo "runners_api_failed"
      echo "=== actions runs for approved tip (read-only) ==="
      gh api "repos/techadv50-boop/EarthVision_Enterprise/actions/runs?head_sha=${APPROVED_TIP}&per_page=20" \
        --jq '{count:(.workflow_runs|length), runs:[.workflow_runs[]|{name,path,head_sha,status,conclusion,event}]}' 2>&1 \
        || echo "actions_runs_api_failed"
    else
      echo "gh_missing=1"
    fi
    echo "forbidden_not_run=gh workflow run deploy-sateye.yml"
  } | tee "$OUT_DIR/13_runner.txt"
else
  echo "INCLUDE_RUNNER_CHECKS=0" | tee "$OUT_DIR/13_runner.txt"
fi

# --- Summary template ---
python3 - "$OUT_DIR" "$APP_DIR" <<'PY'
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
app_dir = sys.argv[2]

def read(name: str) -> str:
    p = out / name
    return p.read_text(errors="replace") if p.exists() else ""

def kv(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    return m.group(1).strip() if m else ""

def img_id(svc: str, text: str) -> str:
    for line in text.splitlines():
        if line.startswith(svc + " Id="):
            m = re.search(r"Id=(\S+)", line)
            return m.group(1) if m else ""
    return ""

def img_digests(svc: str, text: str) -> str:
    for line in text.splitlines():
        if line.startswith(svc + " Id="):
            m = re.search(r"RepoDigests=(\S+)", line)
            return m.group(1) if m else ""
    return ""

ident = read("01_identity.txt")
git = read("04_git.txt")
img = read("06_images.txt")
fp = read("05_fingerprints.txt")
base = read("14_baseline_and_config.txt")
envn = read("12_env_names.txt")
runner = read("13_runner.txt")

ev_present = "yes" if ("EV_PACK_" in envn and "no_EV_PACK_env_names" not in envn) else "no"
runs_api = "ok" if ("\"conclusion\": \"success\"" in runner or '"conclusion":"success"' in runner or "conclusion" in runner and "actions_runs_api_failed" not in runner) else (
    "fail" if "actions_runs_api_failed" in runner or "runners_api_failed" in runner else "unknown"
)
if "gh_missing=1" in runner:
    runs_api = "skipped"
if "INCLUDE_RUNNER_CHECKS=0" in runner:
    runs_api = "skipped"

summary = "\n".join([
    f"hostname={kv(ident, 'hostname')}",
    "compose_project=(see 02_compose_project.txt)",
    f"app_dir={app_dir}",
    f"live_branch={kv(git, 'branch')}",
    f"live_commit={kv(git, 'commit')}",
    f"baseline_1e71b7a_ancestor={kv(git, 'baseline_1e71b7a_ancestor') or kv(base, 'baseline_ancestor')}",
    f"backend_image_id={img_id('backend', img)}",
    f"backend_repo_digest={img_digests('backend', img)}",
    f"frontend_image_id={img_id('frontend', img)}",
    f"frontend_repo_digest={img_digests('frontend', img)}",
    f"env_sha256={kv(fp, 'env_sha256')}",
    f"compose_sha256={kv(fp, 'compose_sha256')}",
    "runner_status=(see 13_runner.txt)",
    f"actions_runs_api={runs_api}",
    f"tools_runtime_http={kv(base, 'public_tools_runtime_http') or kv(base, 'local_tools_runtime_http')}",
    f"composites_http={kv(base, 'public_composites_http')}",
    f"ev_pack_env_names_present={ev_present}",
    "changes_made=none",
    "",
])
(out / "00_return_summary.txt").write_text(summary, encoding="utf-8")
print(summary, end="")
PY

{
  echo "e19c_inventory_complete=1"
  echo "out=$OUT_DIR"
  echo "file_count=$(find "$OUT_DIR" -type f | wc -l | tr -d ' ')"
  find "$OUT_DIR" -type f | sort
} | tee "$OUT_DIR/15_manifest.txt"

# Secret sniff (best-effort)
if grep -R -E -i '(BEGIN (RSA |OPENSSH )?PRIVATE KEY|postgresql://[^<]|postgres://[^<]|password[[:space:]]*[:=][[:space:]]*[^<:[:space:]]{4,})' "$OUT_DIR" \
  --exclude='09_compose_redacted.yml' 2>/dev/null | grep -v '<redacted>' | head -5; then
  echo "WARNING: possible secret-like strings detected — scrub before sharing" | tee "$OUT_DIR/STOP_SECRETS.txt"
else
  echo "secret_sniff=clean_or_redacted" | tee -a "$OUT_DIR/15_manifest.txt"
fi

log "complete — review $OUT_DIR/00_return_summary.txt then share sanitized files"
ls -la "$OUT_DIR"
