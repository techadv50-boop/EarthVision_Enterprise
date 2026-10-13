#!/usr/bin/env bash
# Stage E1.9C-R2 — Read-only production inventory helper (hardened + typed fields).
#
# Identity mismatches ALWAYS stop (SKIP_HOST_CHECK is rejected if set).
# Does not run `docker compose config`, does not dump secret values,
# does not write health response bodies to disk, does not trigger workflows.
#
# Usage:
#   OUT_DIR=/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ) \
#   APP_DIR=/opt/earthvision \
#   bash scripts/e19c_operator_inventory.sh
#
# Optional env:
#   EXPECTED_HOST=zhzh
#   EXPECTED_PROJECT=sateye-fz2ic4
#   INCLUDE_RUNNER_CHECKS=1|0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export APP_DIR="${APP_DIR:-/opt/earthvision}"
export OUT_DIR="${OUT_DIR:-}"
export EXPECTED_HOST="${EXPECTED_HOST:-zhzh}"
export EXPECTED_PROJECT="${EXPECTED_PROJECT:-sateye-fz2ic4}"
export EXPECTED_BASELINE="${EXPECTED_BASELINE:-1e71b7abaa0fa8d4b70225d949afc8ae79923bb6}"
export APPROVED_TIP="${APPROVED_TIP:-e3012ce0a26e049d0af981d5994d0d829c3b647e}"
export INCLUDE_RUNNER_CHECKS="${INCLUDE_RUNNER_CHECKS:-1}"

if [[ -z "${OUT_DIR}" ]]; then
  printf '[e19c] ERROR: OUT_DIR is required (absolute path under /tmp, /var/tmp, or $HOME)\n' >&2
  exit 1
fi

# Refuse known bypass flag if present in environment (any value, including empty)
if [[ -n "${SKIP_HOST_CHECK+x}" ]]; then
  printf '[e19c] ERROR: SKIP_HOST_CHECK is not supported and must not be set\n' >&2
  exit 1
fi

export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "${SCRIPT_DIR}/e19c_inventory_lib.py"
