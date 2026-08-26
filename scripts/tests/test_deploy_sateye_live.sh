#!/usr/bin/env bash
# Unit / parser tests for scripts/deploy_sateye_live.sh (no live server access).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/deploy_sateye_live.sh"
PASS=0
FAIL=0

assert_ok() {
  local name="$1"
  shift
  if "$@" >/tmp/deploy-test-out.$$ 2>/tmp/deploy-test-err.$$; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name (exit $?)" >&2
    sed 's/^/  stderr: /' /tmp/deploy-test-err.$$ >&2 || true
    FAIL=$((FAIL + 1))
  fi
  rm -f /tmp/deploy-test-out.$$ /tmp/deploy-test-err.$$
}

# shellcheck source=scripts/deploy_sateye_live.sh
export DEPLOY_SATEYE_TEST_MODE=1
source "$SCRIPT"

test_dirty_allowlisted_and_spaces() {
  local tmp unexpected=() entry path
  tmp="$(mktemp -d)"
  (
    cd "$tmp"
    git init -q
    git config user.email t@t
    git config user.name t
    mkdir -p cache logs uploads backups backend "dir with spaces"
    echo x >tracked.txt
    git add tracked.txt
    git commit -qm init
    echo c >docker-compose.yml
    echo r >backend/requirements.txt
    echo k >cache/.gitkeep
    echo k >logs/.gitkeep
    echo k >uploads/.gitkeep
    echo s >backups/earthvision_before_cursor_migration.sql
    echo o >docker-compose.cursor.original.yml

    while IFS= read -r -d '' entry; do
      [[ -z "$entry" ]] && continue
      path="${entry:3}"
      is_allowlisted_path "$path" || unexpected+=("$path")
    done < <(git status --porcelain -z -uall)
    [[ ${#unexpected[@]} -eq 0 ]]
  )
  local rc=$?
  rm -rf "$tmp"
  return "$rc"
}

test_unexpected_dirty_path() {
  local tmp unexpected=() entry path
  tmp="$(mktemp -d)"
  (
    cd "$tmp"
    git init -q
    git config user.email t@t
    git config user.name t
    mkdir -p backups "dir with spaces"
    echo x >tracked.txt
    git add tracked.txt
    git commit -qm init
    echo s >backups/earthvision_before_cursor_migration.sql
    echo bad >backups/other.sql
    echo bad >"dir with spaces/bad file.txt"

    while IFS= read -r -d '' entry; do
      [[ -z "$entry" ]] && continue
      path="${entry:3}"
      is_allowlisted_path "$path" || unexpected+=("$path")
    done < <(git status --porcelain -z -uall)

    [[ ${#unexpected[@]} -eq 2 ]]
    printf '%s\n' "${unexpected[@]}" | grep -Fxq 'backups/other.sql'
    printf '%s\n' "${unexpected[@]}" | grep -Fxq 'dir with spaces/bad file.txt'
  )
  local rc=$?
  rm -rf "$tmp"
  return "$rc"
}

expect_fail_subshell() {
  # Returns 0 if the subshell fails (expected), 1 if it succeeds unexpectedly.
  if "$@"; then
    return 1
  fi
  return 0
}

test_preserve_success() {
  local app preserve
  app="$(mktemp -d)"
  preserve="$(mktemp -d)/preserve"
  mkdir -p "$app/backend"
  echo 'compose-live' >"$app/docker-compose.yml"
  echo 'reqs-live' >"$app/backend/requirements.txt"
  (
    cd "$app"
    APP_DIR="$app"
    PRESERVE_DIR="$preserve"
    preservation_ok=0
    preserve_server_overlays
    [[ "$preservation_ok" == "1" ]]
    [[ -f "$PRESERVE_DIR/docker-compose.yml" ]]
    [[ -f "$PRESERVE_DIR/backend-requirements.txt" ]]
    [[ "$(sha256_file docker-compose.yml)" == "$(sha256_file "$PRESERVE_DIR/docker-compose.yml")" ]]
    [[ "$(sha256_file backend/requirements.txt)" == "$(sha256_file "$PRESERVE_DIR/backend-requirements.txt")" ]]
    require_preservation_ok
  )
  local rc=$?
  rm -rf "$app" "$(dirname "$preserve")"
  return "$rc"
}

test_preserve_dir_not_writable() {
  local app parent preserve
  app="$(mktemp -d)"
  parent="$(mktemp -d)/locked"
  mkdir -p "$parent"
  chmod 555 "$parent"
  preserve="$parent/preserve"
  mkdir -p "$app/backend"
  echo 'compose-live' >"$app/docker-compose.yml"
  echo 'reqs-live' >"$app/backend/requirements.txt"
  expect_fail_subshell bash -c "
    set -euo pipefail
    export DEPLOY_SATEYE_TEST_MODE=1
    # shellcheck disable=SC1091
    source '$SCRIPT'
    cd '$app'
    APP_DIR='$app'
    PRESERVE_DIR='$preserve'
    preservation_ok=0
    preserve_server_overlays
  "
  local rc=$?
  chmod 755 "$parent" 2>/dev/null || true
  rm -rf "$app" "$(dirname "$parent")"
  return "$rc"
}

test_preserve_copy_failure() {
  local app preserve
  app="$(mktemp -d)"
  preserve="$(mktemp -d)/preserve"
  mkdir -p "$app/backend"
  echo 'compose-live' >"$app/docker-compose.yml"
  expect_fail_subshell bash -c "
    set -euo pipefail
    export DEPLOY_SATEYE_TEST_MODE=1
    source '$SCRIPT'
    cd '$app'
    APP_DIR='$app'
    PRESERVE_DIR='$preserve'
    preservation_ok=0
    preserve_server_overlays
  "
  local rc=$?
  rm -rf "$app" "$(dirname "$preserve")"
  return "$rc"
}

test_missing_preserved_file_blocks_restore() {
  local app preserve
  app="$(mktemp -d)"
  preserve="$(mktemp -d)/preserve"
  mkdir -p "$app/backend"
  echo 'compose-live' >"$app/docker-compose.yml"
  echo 'reqs-live' >"$app/backend/requirements.txt"
  expect_fail_subshell bash -c "
    set -euo pipefail
    export DEPLOY_SATEYE_TEST_MODE=1
    source '$SCRIPT'
    cd '$app'
    APP_DIR='$app'
    PRESERVE_DIR='$preserve'
    preserve_server_overlays
    rm -f \"\$PRESERVE_DIR/backend-requirements.txt\"
    restore_server_overlays
  "
  local rc=$?
  rm -rf "$app" "$(dirname "$preserve")"
  return "$rc"
}

test_checksum_mismatch_blocks_restore() {
  local app preserve
  app="$(mktemp -d)"
  preserve="$(mktemp -d)/preserve"
  mkdir -p "$app/backend"
  echo 'compose-live' >"$app/docker-compose.yml"
  echo 'reqs-live' >"$app/backend/requirements.txt"
  expect_fail_subshell bash -c "
    set -euo pipefail
    export DEPLOY_SATEYE_TEST_MODE=1
    source '$SCRIPT'
    cd '$app'
    APP_DIR='$app'
    PRESERVE_DIR='$preserve'
    preserve_server_overlays
    echo tampered >\"\$PRESERVE_DIR/docker-compose.yml\"
    restore_server_overlays
  "
  local rc=$?
  rm -rf "$app" "$(dirname "$preserve")"
  return "$rc"
}

test_invariant_blocks_without_preservation() {
  expect_fail_subshell bash -c "
    set -euo pipefail
    export DEPLOY_SATEYE_TEST_MODE=1
    source '$SCRIPT'
    preservation_ok=0
    require_preservation_ok
  "
}

echo "== deploy_sateye_live unit tests =="
assert_ok "writable preserve directory + successful preservation" test_preserve_success
assert_ok "preservation copy failure (missing requirements)" test_preserve_copy_failure
assert_ok "preserve dir not writable fails closed" test_preserve_dir_not_writable
assert_ok "missing preserved file blocks restore" test_missing_preserved_file_blocks_restore
assert_ok "checksum mismatch blocks restore" test_checksum_mismatch_blocks_restore
assert_ok "pre-merge invariant requires preservation_ok=1" test_invariant_blocks_without_preservation
assert_ok "allowlisted dirty paths only" test_dirty_allowlisted_and_spaces
assert_ok "unexpected dirty path + path with spaces" test_unexpected_dirty_path

echo "PASSED=$PASS FAILED=$FAIL"
[[ "$FAIL" -eq 0 ]]
