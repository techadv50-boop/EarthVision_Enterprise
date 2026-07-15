#!/usr/bin/env bash
# Idempotent install for Cursor Cloud Agents (cursor.com/agents).
# Safe to re-run on every agent boot after git pull.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> EarthVision cloud install (root: $ROOT)"

# --- Backend Python venv + deps ---
if [[ ! -d backend/.venv ]]; then
  echo "==> Creating backend/.venv"
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
python -m pip install --upgrade pip wheel setuptools >/dev/null
pip install -r backend/requirements.txt
# CV deps used by detection / terrain (may already be in requirements)
pip install "opencv-python-headless==4.10.0.84" "scipy>=1.11.0" >/dev/null 2>&1 || true

# Backend env (SQLite-friendly defaults for cloud VMs)
if [[ ! -f backend/.env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example backend/.env
  else
    cat > backend/.env <<'EOF'
APP_NAME=EarthVision Enterprise
ENVIRONMENT=development
DEBUG=true
SECRET_KEY=earthvision-cloud-dev-secret-change-me-32chars!!
DATABASE_URL=sqlite+aiosqlite:///./earthvision.db
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173","http://localhost:3000"]
ADMIN_EMAIL=admin@earthvision.io
ADMIN_PASSWORD=EarthVision@Admin2024!
IMAGERY_CACHE_DIR=../cache
IMAGERY_DIR=../imagery
UPLOADS_DIR=../uploads
LOGS_DIR=../logs
EOF
  fi
  # Force SQLite on cloud if compose-style Postgres URL was copied
  sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite+aiosqlite:///./earthvision.db|' backend/.env || true
fi

mkdir -p cache imagery uploads logs

# --- Frontend ---
if [[ -f frontend/package.json ]]; then
  echo "==> npm install (frontend)"
  (cd frontend && npm install --no-fund --no-audit)
  if [[ ! -f frontend/.env ]]; then
    cat > frontend/.env <<'EOF'
VITE_API_URL=/api/v1
VITE_CESIUM_ION_TOKEN=
EOF
  fi
fi

echo "==> Cloud install complete"
echo "    API:  http://localhost:8000  (login admin@earthvision.io / EarthVision@Admin2024!)"
echo "    App:  http://localhost:5173"
