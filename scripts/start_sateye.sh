#!/usr/bin/env bash
# Start SAT EYE on the server (reachable from field clients on the LAN/WAN).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Virtualenv missing. Run ./scripts/install_sateye.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export OFFLINE_MODE="${OFFLINE_MODE:-true}"
export REQUIRE_LOGIN="${REQUIRE_LOGIN:-true}"
export CORS_ALLOW_ALL="${CORS_ALLOW_ALL:-true}"
export MASTER_RESET_CODE="${MASTER_RESET_CODE:-NTZHSS}"
export APP_NAME="${APP_NAME:-SAT EYE}"
export SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
export SERVER_PORT="${SERVER_PORT:-8000}"
UI_HOST="${UI_HOST:-0.0.0.0}"
UI_PORT="${UI_PORT:-5173}"

echo "========================================"
echo "  SAT EYE server (field access)"
echo "  API:  http://${SERVER_HOST}:${SERVER_PORT}"
echo "  UI:   http://${UI_HOST}:${UI_PORT}"
echo "  Login required. Master reset code: ${MASTER_RESET_CODE}"
echo "========================================"

cd backend
uvicorn app.main:app --host "$SERVER_HOST" --port "$SERVER_PORT" --app-dir . &
BACK_PID=$!
cd "$ROOT"

cleanup() {
  kill "$BACK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Show helpful LAN IP if available
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
if [[ -n "${LAN_IP:-}" ]]; then
  echo "Field clients can open: http://${LAN_IP}:${UI_PORT}"
fi

cd frontend
npm run dev -- --host "$UI_HOST" --port "$UI_PORT"
