#!/usr/bin/env bash
# Start SAT EYE offline (backend + frontend) for local PC use.
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
export APP_NAME="${APP_NAME:-SAT EYE}"

echo "Starting SAT EYE backend on :8000 ..."
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir . &
BACK_PID=$!
cd "$ROOT"

cleanup() {
  kill "$BACK_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting SAT EYE UI on :5173 ..."
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
