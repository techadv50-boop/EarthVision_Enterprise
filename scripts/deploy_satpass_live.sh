#!/usr/bin/env bash
# Upload / update SatPass on the VPS that serves https://satpass.xdgen.com
#
# Run on the VPS (not from a laptop cloud agent):
#   sudo -u "$USER" bash scripts/deploy_satpass_live.sh
#
# Preserves /opt/xdgen/.env (Cloudflare tunnel token, SECRET_KEY).
# Never runs docker compose down -v.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/xdgen}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-cursor/satpass-predict-tab-ea6c}"
REMOTE="${REMOTE:-origin}"
REPO_URL="${REPO_URL:-https://github.com/techadv50-boop/EarthVision_Enterprise.git}"
HEALTH_URL_LOCAL="${HEALTH_URL_LOCAL:-http://127.0.0.1:8080/}"
HEALTH_URL_API="${HEALTH_URL_API:-http://127.0.0.1:8000/api/v1/auth/me}"
PUBLIC_URL="${PUBLIC_URL:-https://satpass.xdgen.com/}"

log() { printf '[deploy-satpass] %s\n' "$*"; }
die() { printf '[deploy-satpass] ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

preflight() {
  require_cmd git
  require_cmd docker
  require_cmd curl
  docker compose version >/dev/null 2>&1 || die "docker compose plugin is required"
}

ensure_checkout() {
  if [[ ! -d "$APP_DIR/.git" ]]; then
    log "cloning $REPO_URL → $APP_DIR"
    sudo mkdir -p "$(dirname "$APP_DIR")"
    sudo git clone "$REPO_URL" "$APP_DIR"
    sudo chown -R "$(id -u):$(id -g)" "$APP_DIR"
  fi
  cd "$APP_DIR"
  [[ -f .env ]] || die "missing $APP_DIR/.env — copy .env.example and set CLOUDFLARE_TUNNEL_TOKEN and SECRET_KEY"
  grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env || die "set CLOUDFLARE_TUNNEL_TOKEN in $APP_DIR/.env"
  log "directory=$APP_DIR"
  log ".env present size=$(wc -c < .env | tr -d ' ') sha256=$(sha256_file .env)"
}

update_source() {
  local env_before
  env_before="$(sha256_file .env)"
  git fetch --prune "$REMOTE" "$DEPLOY_BRANCH"
  git checkout "$DEPLOY_BRANCH"
  git merge --ff-only "$REMOTE/$DEPLOY_BRANCH"
  [[ "$(sha256_file .env)" == "$env_before" ]] || die ".env changed during git update — aborting"
  log "branch=$(git branch --show-current) commit=$(git rev-parse --short HEAD)"
}

rebuild() {
  log "building and starting stack (tunnel profile)"
  docker compose --profile tunnel up -d --build --remove-orphans
  docker compose --profile tunnel ps
}

healthcheck() {
  local attempt
  for attempt in $(seq 1 24); do
    if curl -fsS --max-time 10 -o /dev/null "$HEALTH_URL_LOCAL"; then
      log "local homepage OK: $HEALTH_URL_LOCAL"
      break
    fi
    log "local homepage miss (attempt ${attempt})"
    sleep 5
    [[ "$attempt" -eq 24 ]] && die "local homepage did not come up at $HEALTH_URL_LOCAL"
  done
  if curl -fsS --max-time 10 -o /dev/null "$HEALTH_URL_API"; then
    log "local API reachable: $HEALTH_URL_API"
  else
    log "WARNING: local API check failed ($HEALTH_URL_API)"
  fi
  if curl -fsS --max-time 20 -o /dev/null "$PUBLIC_URL"; then
    log "public site OK: $PUBLIC_URL"
  else
    log "WARNING: $PUBLIC_URL is not reachable yet. Add the satpass Cloudflare Tunnel hostname (see docs/HOSTING.md)."
  fi
}

main() {
  preflight
  ensure_checkout
  update_source
  rebuild
  healthcheck
  log "done. Login: operator@satpass.xdgen.com / pak123"
}

main "$@"
