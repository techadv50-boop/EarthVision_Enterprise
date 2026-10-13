#!/usr/bin/env bash
# Read-only deployment preflight capture (B-DIGESTS code portion).
#
# Records commit, image IDs/digests, compose fingerprints, and rollback refs.
# Does NOT modify containers, volumes, or credentials.
#
# E1.9A: do not run against production unless/until explicitly authorized.
# Local/fixture mode: set DEPLOY_PREFLIGHT_DIR to a fake app dir for tests.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/earthvision}"
OUT_DIR="${DEPLOY_PREFLIGHT_OUT:-./preflight-out}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

die() { printf '[preflight] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[preflight] %s\n' "$*"; }

# Safety: refuse known production path unless DEPLOY_PREFLIGHT_ALLOW_PROD=1
if [[ "$APP_DIR" == "/opt/earthvision" && "${DEPLOY_PREFLIGHT_ALLOW_PROD:-0}" != "1" ]]; then
  die "refusing /opt/earthvision without DEPLOY_PREFLIGHT_ALLOW_PROD=1 (E1.9A: not authorized for prod)"
fi

[[ -d "$APP_DIR" ]] || die "APP_DIR missing: $APP_DIR"
mkdir -p "$OUT_DIR"
cd "$APP_DIR"

{
  echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "app_dir=$APP_DIR"
  echo "hostname=$(hostname 2>/dev/null || true)"
  if [[ -d .git ]]; then
    echo "branch=$(git branch --show-current 2>/dev/null || true)"
    echo "commit=$(git rev-parse HEAD 2>/dev/null || true)"
    echo "commit_short=$(git rev-parse --short HEAD 2>/dev/null || true)"
  else
    echo "branch="
    echo "commit="
    echo "commit_short="
  fi
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
} | tee "$OUT_DIR/preflight_meta.txt"

# Image digests (best-effort; skip if docker unavailable)
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  {
    echo "=== docker compose images ==="
    docker compose images 2>/dev/null || true
    echo "=== backend/frontend inspect ==="
    for svc in backend frontend; do
      id="$(docker compose images -q "$svc" 2>/dev/null | head -1 || true)"
      if [[ -n "$id" ]]; then
        docker image inspect "$id" --format "$svc Id={{.Id}} RepoDigests={{json .RepoDigests}} Created={{.Created}}" 2>/dev/null || true
      else
        echo "$svc Id=MISSING"
      fi
    done
  } | tee "$OUT_DIR/preflight_images.txt"
else
  echo "docker_unavailable=1" | tee "$OUT_DIR/preflight_images.txt"
fi

# Rollback reference stub
cat >"$OUT_DIR/rollback_refs.txt" <<EOF
PRIOR_GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo UNKNOWN)
PRIOR_COMPOSE_SHA256=$( [[ -f $COMPOSE_FILE ]] && sha256sum "$COMPOSE_FILE" | awk '{print $1}' || echo UNKNOWN )
PRIOR_REQUIREMENTS_SHA256=$( [[ -f backend/requirements.txt ]] && sha256sum backend/requirements.txt | awk '{print $1}' || echo UNKNOWN )
PRIOR_ENV_SHA256=$( [[ -f .env ]] && sha256sum .env | awk '{print $1}' || echo UNKNOWN )
PRESERVE_DIR=\${PRESERVE_DIR:-/home/zh/earthvision-deploy-preserve}
EOF

log "wrote $OUT_DIR"
ls -la "$OUT_DIR"
