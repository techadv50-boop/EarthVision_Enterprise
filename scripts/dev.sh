#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Starting SAT EYE — Eye In Sky…"
cd "$ROOT/backend"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACK_PID=$!

cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
wait
