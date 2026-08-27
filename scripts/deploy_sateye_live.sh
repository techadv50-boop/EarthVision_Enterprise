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
#     (copied to /home/zh/earthvision-deploy-preserve — OUTSIDE the Git tree)
#   - PostgreSQL Docker volume (pgdata)
#   - uploads / cache / imagery / logs bind mounts
#
# Preservation is FAIL-CLOSED: git checkout / git merge never run unless
# preservation_ok=1 after verified copies + checksums.
#
# Never uses: git reset --hard, docker compose down -v, or secret printing.
# Never stores .env in the preserve directory.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/earthvision}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-cursor/scene-download-eye-5d6d}"
REMOTE="${REMOTE:-origin}"
# Must stay outside APP_DIR and be writable by the runner user (zh).
PRESERVE_DIR="${PRESERVE_DIR:-/home/zh/earthvision-deploy-preserve}"
HEALTH_URLS=(
  "${HEALTH_URL_LOCAL:-http://127.0.0.1/health}"
  "${HEALTH_URL_BACKEND:-http://127.0.0.1:8000/health}"
)
PUBLIC_HEALTH_URL="${HEALTH_URL_PUBLIC:-https://sateye.xdgen.com/health}"

# Exact dirty-tree allowlist only (no directory wildcards).
ALLOWLISTED_PATHS=(
  "docker-compose.yml"
  "backend/requirements.txt"
  "cache/.gitkeep"
  "logs/.gitkeep"
  "uploads/.gitkeep"
  "backups/earthvision_before_cursor_migration.sql"
  "docker-compose.cursor.original.yml"
)

# Set to 1 only after verified preservation of both overlay files.
preservation_ok=0
COMPOSITE_SHA=""
REQUIREMENTS_SHA=""
ENV_SHA=""

log() { printf '[deploy-sateye] %s\n' "$*"; }
die() {
  printf '[deploy-sateye] ERROR: %s\n' "$*" >&2
  if [[ "${DEPLOY_SATEYE_TEST_MODE:-0}" == "1" ]]; then
    return 1
  fi
  exit 1
}

abort_before_docker() {
  printf '[deploy-sateye] ERROR: %s\n' "$*" >&2
  printf '[deploy-sateye] ERROR: Deployment aborted before Docker restart; preserved overlays remain available.\n' >&2
  if [[ "${DEPLOY_SATEYE_TEST_MODE:-0}" == "1" ]]; then
    return 1
  fi
  exit 1
}

# After checkout/merge has (or may have) mutated overlay files: restore first, then abort.
abort_after_overlay_mutation() {
  local reason="$1"
  printf '[deploy-sateye] ERROR: %s\n' "$reason" >&2

  if ! restore_server_overlays; then
    printf '[deploy-sateye] ERROR: overlay restore after failure also failed; copies remain in PRESERVE_DIR=%s\n' "$PRESERVE_DIR" >&2
    if [[ "${DEPLOY_SATEYE_TEST_MODE:-0}" == "1" ]]; then
      return 1
    fi
    exit 1
  fi

  local env_after
  env_after="$(sha256_file .env)"
  if [[ "$env_after" != "$ENV_SHA" ]]; then
    printf '[deploy-sateye] ERROR: .env checksum changed during failed deploy\n' >&2
    if [[ "${DEPLOY_SATEYE_TEST_MODE:-0}" == "1" ]]; then
      return 1
    fi
    exit 1
  fi

  printf '[deploy-sateye] ERROR: Deployment aborted before Docker restart; preserved overlays were restored.\n' >&2
  if [[ "${DEPLOY_SATEYE_TEST_MODE:-0}" == "1" ]]; then
    return 1
  fi
  exit 1
}

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

# Parse git status --porcelain -z -uall correctly for modified/deleted/untracked
# (including files inside untracked dirs), renames, and paths containing spaces.
# Unknown paths abort deploy (nothing is discarded). Directory wildcards are NOT
# allowed — only exact paths in ALLOWLISTED_PATHS.
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
  done < <(git status --porcelain -z -uall)

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
  log "PRESERVE_DIR=$PRESERVE_DIR"
  log "branch=$branch"
  log "commit=$(git rev-parse HEAD)"
  log "short=$(git rev-parse --short HEAD)"
  log ".env $(env_fingerprint .env)"
  log "working tree:"
  git status --porcelain -uall || true
  log "docker compose services:"
  docker compose ps || docker-compose ps || die "docker compose ps failed"
}

ensure_preserve_dir() {
  case "$PRESERVE_DIR" in
    "$APP_DIR"|"$APP_DIR"/*)
      die "PRESERVE_DIR must be outside the Git repo ($APP_DIR); got: $PRESERVE_DIR"
      ;;
  esac

  mkdir -p "$PRESERVE_DIR" || die "cannot create PRESERVE_DIR=$PRESERVE_DIR"
  chmod 700 "$PRESERVE_DIR" || die "cannot chmod PRESERVE_DIR=$PRESERVE_DIR"

  local probe="$PRESERVE_DIR/.write-test.$$"
  if ! ( : >"$probe" ) 2>/dev/null; then
    die "PRESERVE_DIR is not writable: $PRESERVE_DIR"
  fi
  rm -f "$probe"

  # Never place secrets here.
  [[ ! -e "$PRESERVE_DIR/.env" ]] || die "refusing to keep .env inside preserve dir $PRESERVE_DIR"
}

# FAIL-CLOSED preservation. Sets preservation_ok=1 only on full success.
# Must complete before any git checkout / git merge.
preserve_server_overlays() {
  preservation_ok=0
  COMPOSITE_SHA=""
  REQUIREMENTS_SHA=""

  log "PRESERVE_DIR=$PRESERVE_DIR"
  ensure_preserve_dir

  [[ -f docker-compose.yml ]] || die "live docker-compose.yml missing; cannot preserve"
  [[ -f backend/requirements.txt ]] || die "live backend/requirements.txt missing; cannot preserve"

  COMPOSITE_SHA="$(sha256_file docker-compose.yml)"
  REQUIREMENTS_SHA="$(sha256_file backend/requirements.txt)"

  # Overlays only — never copy .env into PRESERVE_DIR.
  cp -a docker-compose.yml "$PRESERVE_DIR/docker-compose.yml" \
    || die "failed to copy docker-compose.yml into PRESERVE_DIR"
  cp -a backend/requirements.txt "$PRESERVE_DIR/backend-requirements.txt" \
    || die "failed to copy backend/requirements.txt into PRESERVE_DIR"

  chmod 600 "$PRESERVE_DIR/docker-compose.yml" "$PRESERVE_DIR/backend-requirements.txt" || true

  [[ -f "$PRESERVE_DIR/docker-compose.yml" ]] \
    || die "preserved docker-compose.yml missing after copy"
  [[ -f "$PRESERVE_DIR/backend-requirements.txt" ]] \
    || die "preserved backend/requirements.txt missing after copy"

  local p_compose p_reqs
  p_compose="$(sha256_file "$PRESERVE_DIR/docker-compose.yml")"
  p_reqs="$(sha256_file "$PRESERVE_DIR/backend-requirements.txt")"

  [[ "$p_compose" == "$COMPOSITE_SHA" ]] \
    || die "preserved docker-compose.yml checksum mismatch"
  [[ "$p_reqs" == "$REQUIREMENTS_SHA" ]] \
    || die "preserved backend/requirements.txt checksum mismatch"

  preservation_ok=1
  log "preservation succeeded"
  log "preservation checksums compose=$COMPOSITE_SHA requirements=$REQUIREMENTS_SHA"
}

require_preservation_ok() {
  [[ "${preservation_ok}" == "1" ]] \
    || die "pre-merge invariant failed: preservation_ok!=1 (refusing git checkout/merge)"
}

restore_server_overlays() {
  [[ -f "$PRESERVE_DIR/docker-compose.yml" ]] \
    || abort_before_docker "missing preserved docker-compose.yml"
  [[ -f "$PRESERVE_DIR/backend-requirements.txt" ]] \
    || abort_before_docker "missing preserved backend/requirements.txt"

  cp -a "$PRESERVE_DIR/docker-compose.yml" docker-compose.yml \
    || abort_before_docker "failed to restore docker-compose.yml"
  cp -a "$PRESERVE_DIR/backend-requirements.txt" backend/requirements.txt \
    || abort_before_docker "failed to restore backend/requirements.txt"

  log "overlays restored"

  local live_compose live_reqs
  live_compose="$(sha256_file docker-compose.yml)"
  live_reqs="$(sha256_file backend/requirements.txt)"

  [[ "$live_compose" == "$COMPOSITE_SHA" ]] \
    || abort_before_docker "restored docker-compose.yml checksum mismatch (expected $COMPOSITE_SHA got $live_compose)"
  [[ "$live_reqs" == "$REQUIREMENTS_SHA" ]] \
    || abort_before_docker "restored backend/requirements.txt checksum mismatch (expected $REQUIREMENTS_SHA got $live_reqs)"

  # Preserve copies must still exist for recovery.
  [[ -f "$PRESERVE_DIR/docker-compose.yml" ]] \
    || abort_before_docker "preserve copy of docker-compose.yml disappeared"
  [[ -f "$PRESERVE_DIR/backend-requirements.txt" ]] \
    || abort_before_docker "preserve copy of backend/requirements.txt disappeared"

  log "overlay checksums verified compose=$live_compose requirements=$live_reqs"
}

update_source_ff_only() {
  local before after remote_sha env_after

  ENV_SHA="$(sha256_file .env)"
  before="$(git rev-parse HEAD)"

  log "fetching $REMOTE $DEPLOY_BRANCH"
  git fetch --prune "$REMOTE" "$DEPLOY_BRANCH"

  remote_sha="$(git rev-parse "$REMOTE/$DEPLOY_BRANCH")"
  log "local=$before"
  log "remote=$remote_sha"

  if [[ "$before" == "$remote_sha" ]]; then
    log "Already up to date"
    return 2
  fi

  # FAIL-CLOSED: must succeed before any checkout/merge mutates the tree.
  preserve_server_overlays
  require_preservation_ok

  # Clear allowlisted overlay modifications so ff-only merge can proceed.
  # Does NOT use reset --hard. Does NOT touch .env (untracked/gitignored).
  # If checkout/merge fails after mutating overlays, restore immediately.
  log "merge started"
  if ! git checkout HEAD -- docker-compose.yml backend/requirements.txt; then
    abort_after_overlay_mutation "git checkout of overlay files failed"
    return 1
  fi
  if ! git merge --ff-only "$REMOTE/$DEPLOY_BRANCH"; then
    abort_after_overlay_mutation "git merge --ff-only failed"
    return 1
  fi
  log "merge completed"

  restore_server_overlays || return 1

  after="$(git rev-parse HEAD)"
  env_after="$(sha256_file .env)"
  [[ "$env_after" == "$ENV_SHA" ]] \
    || abort_before_docker ".env checksum changed during deploy"
  [[ -f .env ]] || abort_before_docker ".env missing after merge"

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

restart_backend_only() {
  log "restarting backend container (recovery for hung / 502 origin)"
  docker compose up -d --force-recreate --no-deps backend
  # Give uvicorn a moment to bind before health checks
  sleep 5
  log "compose status after backend recreate:"
  docker compose ps
}

# Update ADMIN_PASSWORD in live .env without printing the value.
# Default password reset target: Alihussain (override with ADMIN_PASSWORD_RESET).
# Set RESET_ADMIN_PASSWORD=0 to skip.
ADMIN_PASSWORD_SYNCED=0
sync_admin_password_env() {
  local new_pw="${ADMIN_PASSWORD_RESET:-Alihussain}"
  local do_sync="${RESET_ADMIN_PASSWORD:-1}"
  ADMIN_PASSWORD_SYNCED=0
  if [[ "$do_sync" != "1" ]]; then
    log "skipping ADMIN_PASSWORD sync (RESET_ADMIN_PASSWORD!=1)"
    return 0
  fi
  [[ -f .env ]] || die "missing .env for admin password sync"
  local before after
  before="$(sha256_file .env)"
  if grep -qE '^ADMIN_PASSWORD=' .env; then
    awk -v pw="$new_pw" '
      BEGIN { done=0 }
      /^ADMIN_PASSWORD=/ {
        print "ADMIN_PASSWORD=" pw
        done=1
        next
      }
      { print }
      END {
        if (!done) print "ADMIN_PASSWORD=" pw
      }
    ' .env > .env.tmp_admin
    mv .env.tmp_admin .env
    chmod 600 .env || true
  else
    printf '\nADMIN_PASSWORD=%s\n' "$new_pw" >> .env
    chmod 600 .env || true
  fi
  after="$(sha256_file .env)"
  if [[ "$before" != "$after" ]]; then
    ADMIN_PASSWORD_SYNCED=1
    log "ADMIN_PASSWORD synced in .env (value not printed; checksum changed)"
  else
    log "ADMIN_PASSWORD already at requested value in .env"
  fi
}

local_health_ok() {
  local url
  for url in "${HEALTH_URLS[@]}"; do
    if curl -fsS --max-time 15 "$url" >/dev/null; then
      return 0
    fi
  done
  return 1
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

  # Ops password reset (default on): keep live ADMIN_PASSWORD in sync before restart
  sync_admin_password_env

  set +e
  update_source_ff_only
  update_rc=$?
  set -e

  if [[ "$update_rc" -eq 2 ]]; then
    log "Already up to date"
    if local_health_ok && [[ "$ADMIN_PASSWORD_SYNCED" -eq 0 ]] && [[ "${FORCE_REBUILD:-0}" != "1" ]]; then
      log "local health OK and password unchanged — skipping rebuild"
      healthcheck
      log "done (no changes)"
      exit 0
    fi
    if ! local_health_ok; then
      log "local health FAILED — forcing full app rebuild/restart (Cloudflare 502 recovery)"
    elif [[ "$ADMIN_PASSWORD_SYNCED" -eq 1 ]]; then
      log "ADMIN_PASSWORD changed — rebuilding so bootstrap applies the new hash"
    else
      log "FORCE_REBUILD=1 — rebuilding"
    fi
    rebuild_and_restart
    healthcheck
    log "done (recovery) commit=$(git rev-parse --short HEAD)"
    exit 0
  fi
  if [[ "$update_rc" -ne 0 ]]; then
    abort_before_docker "source update failed (rc=$update_rc); database and uploads were not wiped"
  fi

  rebuild_and_restart
  healthcheck
  log "deployment complete commit=$(git rev-parse --short HEAD)"
}

# Allow unit tests to source this file without running main.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
