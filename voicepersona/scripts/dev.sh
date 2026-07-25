#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  (cd "$ROOT/frontend" && npm install)
fi

php -S 127.0.0.1:8790 -t "$ROOT/api" "$ROOT/api/router.php" &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1
