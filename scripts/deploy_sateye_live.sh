#!/usr/bin/env bash
# SAT EYE — safe manual live deploy for /opt/earthvision (online Eye In Sky).
# Intended to run on the self-hosted runner host (sateye-live).
#
# Execute this script from the Actions/runner workspace (or any path outside
# APP_DIR). Do NOT copy it into /opt/earthvision before preflight — that would
# dirty the live checkout and fail the allowlist check.
#
# Preserves:
#   - /opt/earthvision/.env  (never overwritten from Git)
#   - server-specific docker-compose.yml and backend/requirements.txt
#     (copied to /opt/earthvision-deploy-preserve — OUTSIDE the Git tree)
#   - PostgreSQL Docker volume (pgdata)
#   - uploads / cache / imagery / logs bind mounts
#
# Never uses: git reset --hard, docker compose down -v, or secret printing.
# Never stores .env in the preserve directory.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/earthvision}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-cursor/scene-download-eye-5d6d}"
REMOTE="${REMOTE:-origin}"
# Must stay outside APP_DIR so it never dirties the live Git working tree.
PRESERVE_DIR="${PRESERVE_DIR:-/opt/earthvision-deploy-preserve}"
HEALTH_URLS=(
  "${HEALTH_URL_LOCAL:-http://127.0.0.1/health}"
  "${HEALTH_URL_BACKEND:-http://127.0.0.1:8000/health}"
)
PUBLIC_HEALTH_URL="${HEALTH_URL_PUBLIC:-https://sateye.xdgen.com/health}"

# Exact dirty-tree allowlist only (no directory wildcards).
# Server overlays restored across FF merge:
#   docker-compose.yml, backend/requirements.txt
# Known live-server artifacts that must not abort deploy and must not be deleted:
#   cache/.gitkeep, logs/.gitkeep, uploads/.gitkeep,
#   backups/earthvision_before_cursor_migration.sql,
#   docker-compose.cursor.original.yml
ALLOWLISTED_PATHS=(
  "docker-compose.yml"
  "backend/requirements.txt"
  "cache/.gitkeep"
  "logs/.gitkeep"
  "uploads/.gitkeep"
  "backups/earthvision_before_cursor_migration.sql"
  "docker-compose.cursor.original.yml"
)

log() { printf '[deploy-sateye] %s\n' "$*"; }
die() { printf '[deploy-sateye] ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

# Never print .env contents — only presence + checksum.
env_fingerprint() {
  local f="$1"
  local size
  size="$(wc -c <"$f" | tr -d ' ')"
  printf 'present size=%s sha256=%s' "$size" "$(sha256_file "$f")"
}

is_allowlisted_path() {
  local candidate="$1"
  local allowed
  for allowed in "${ALLOWLISTED_PATHS[@]}"; do
    if [[ "$candidate" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

# Parse git status --porcelain -z correctly for modified/deleted/untracked/renames
# and paths containing spaces. Unknown paths abort deploy (nothing is discarded).
assert_only_allowlisted_dirty() {
  local unexpected=()
  local entry status path other
  local has_dirty=0

  while IFS= read -r -d '' entry; do
    [[ -z "$entry" ]] && continue
    has_dirty=1
    # Record format: "XY <path>" (XY = two status chars, then space, then path).
    if [[ "${#entry}" -lt 4 ]]; then
      unexpected+=("<malformed-status:${entry}>")
      continue
    fi
    status="${entry:0:2}"
    path="${entry:3}"

    if ! is_allowlisted_path "$path"; then
      unexpected+=("$path")
    fi

    # Rename (R) / copy (C): -z emits a second NUL-terminated path field.
    if [[ "${status:0:1}" == "R" || "${status:0:1}" == "C" || "${status:1:1}" == "R" || "${status:1:1}" == "C" ]]; then
      if IFS= read -r -d '' other; then
        if [[ -n "$other" ]] && ! is_allowlisted_path "$other"; then
          unexpected+=("$other")
        fi
      fi
    fi
  done < <(git status --porcelain -z)

  if [[ "$has_dirty" -eq 0 ]]; then
    return 0
  fi

  if [[ "${#unexpected[@]}" -gt 0 ]]; then
    printf '%s\n' "${unexpected[@]}" >&2
    die "unexpected dirty paths (aborting; will not discard). Allowlist: ${ALLOWLISTED_PATHS[*]}"
  fi
  log "dirty paths are allowlisted only — will not discard them"
}

preflight() {
  require_cmd git
  require_cmd docker
  require_cmd curl
  require_cmd sha256sum

  [[ -d "$APP_DIR" ]] || die "app directory missing: $APP_DIR"
  cd "$APP_DIR"

  [[ "$(pwd -P)" == "$(readlink -f "$APP_DIR")" ]] || log "working directory: $(pwd)"

  [[ -d .git ]] || die "$APP_DIR is not a git repository"
  [[ -f .env ]] || die "missing $APP_DIR/.env (refusing to deploy without live env)"

  local branch
  branch="$(git branch --show-current || true)"
  [[ "$branch" == "$DEPLOY_BRANCH" ]] || die "expected branch '$DEPLOY_BRANCH', found '${branch:-detached}'"

  log "preflight ok"
  log "directory=$APP_DIR"
  log "branch=$branch"
  log "commit=$(git rev-parse HEAD)"
  log "short=$(git rev-parse --short HEAD)"
  log ".env $(env_fingerprint .env)"
  log "working tree:"
  git status --porcelain || true
  log "docker compose services:"
  docker compose ps || docker-compose ps || die "docker compose ps failed"
}

ensure_preserve_dir() {
  case "$PRESERVE_DIR" in
    "$APP_DIR"|"$APP_DIR"/*)
      die "PRESERVE_DIR must be outside the Git repo ($APP_DIR); got: $PRESERVE_DIR"
      ;;
  esac
  mkdir -p "$PRESERVE_DIR"
  chmod 700 "$PRESERVE_DIR"
  # Never place secrets here.
  [[ ! -e "$PRESERVE_DIR/.env" ]] || die "refusing to keep .env inside preserve dir $PRESERVE_DIR"
}

preserve_server_overlays() {
  ensure_preserve_dir
  # Overlays only — never copy .env into PRESERVE_DIR.
  cp -a docker-compose.yml "$PRESERVE_DIR/docker-compose.yml"
  cp -a backend/requirements.txt "$PRESERVE_DIR/backend-requirements.txt"
  chmod 600 "$PRESERVE_DIR/docker-compose.yml" "$PRESERVE_DIR/backend-requirements.txt" || true
  log "saved server overlays to $PRESERVE_DIR (retained on failure for recovery)"
}

restore_server_overlays() {
  [[ -f "$PRESERVE_DIR/docker-compose.yml" ]] || die "missing preserved docker-compose.yml"
  [[ -f "$PRESERVE_DIR/backend-requirements.txt" ]] || die "missing preserved backend/requirements.txt"
  cp -a "$PRESERVE_DIR/docker-compose.yml" docker-compose.yml
  cp -a "$PRESERVE_DIR/backend-requirements.txt" backend/requirements.txt
  log "restored server overlays (compose + requirements)"
}

update_source_ff_only() {
  local before after remote_sha env_before env_after

  env_before="$(sha256_file .env)"
  before="$(git rev-parse HEAD)"

  log "fetching $REMOTE $DEPLOY_BRANCH"
  git fetch --prune "$REMOTE" "$DEPLOY_BRANCH"

  remote_sha="$(git rev-parse "$REMOTE/$DEPLOY_BRANCH")"
  log "local=$before"
  log "remote=$remote_sha"

  if [[ "$before" == "$remote_sha" ]]; then
    log "Already up to date"
    # Still ensure overlays are the live server copies if they were dirty.
    return 2
  fi

  preserve_server_overlays

  # Clear allowlisted local modifications so ff-only merge can proceed.
  # Does NOT use reset --hard. Does NOT touch .env (untracked/gitignored).
  git checkout HEAD -- docker-compose.yml backend/requirements.txt

  log "merging $REMOTE/$DEPLOY_BRANCH (ff-only)"
  git merge --ff-only "$REMOTE/$DEPLOY_BRANCH"

  restore_server_overlays

  after="$(git rev-parse HEAD)"
  env_after="$(sha256_file .env)"
  [[ "$env_after" == "$env_before" ]] || die ".env checksum changed during deploy — aborting for safety"
  [[ -f .env ]] || die ".env missing after merge"

  log "updated $before -> $after"
  log ".env unchanged ($(env_fingerprint .env))"
  return 0
}

rebuild_and_restart() {
  log "building backend + frontend images"
  docker compose build backend frontend

  # Recreate app containers only. Never down -v. Postgres volume preserved.
  log "starting stack (preserving volumes)"
  docker compose up -d --remove-orphans

  log "compose status after up:"
  docker compose ps
}

healthcheck() {
  local url ok=0
  log "running health checks"
  for url in "${HEALTH_URLS[@]}"; do
    if curl -fsS --max-time 30 "$url" >/dev/null; then
      log "health OK: $url"
      ok=1
      break
    else
      log "health miss: $url"
    fi
  done
  [[ "$ok" -eq 1 ]] || die "local health checks failed"

  if curl -fsS --max-time 30 "$PUBLIC_HEALTH_URL" >/dev/null; then
    log "public health OK: $PUBLIC_HEALTH_URL"
  else
    log "WARNING: public health check failed ($PUBLIC_HEALTH_URL) — local health passed; check Cloudflare/DNS"
  fi
}

main() {
  preflight
  assert_only_allowlisted_dirty

  set +e
  update_source_ff_only
  update_rc=$?
  set -e

  if [[ "$update_rc" -eq 2 ]]; then
    log "Already up to date — skipping rebuild"
    healthcheck
    log "done (no changes)"
    exit 0
  fi
  if [[ "$update_rc" -ne 0 ]]; then
    die "source update failed (rc=$update_rc); database and uploads were not wiped"
  fi

  rebuild_and_restart
  healthcheck
  log "deployment complete commit=$(git rev-parse --short HEAD)"
}

main "$@"
