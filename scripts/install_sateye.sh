#!/usr/bin/env bash
# SAT EYE — Offline PC installation (Linux / macOS / WSL)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "========================================"
echo "  SAT EYE — Offline Earth Observation"
echo "  Local PC installer (no internet runtime)"
echo "========================================"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[ok] Created .env from .env.example (OFFLINE_MODE=true)"
fi

echo "[1/4] Python backend dependencies..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "[2/4] Frontend dependencies..."
cd frontend
npm install
cd "$ROOT"

echo "[3/4] Seed offline basemaps, landmarks, DEM/DTM/DSM..."
PYTHONPATH=backend python - <<'PY'
from app.services.offline_layers_service import OfflineLayersService
from app.services.imagery_stack_service import ImageryStackService
from app.services.gis_tools_catalog import GIS_TOOLS

print("layers:", OfflineLayersService().ensure_seed_data())
print("demo stack images:", ImageryStackService().seed_demo_stack().get("image_count"))
print("gis tools:", len(GIS_TOOLS))
PY

echo "[4/4] Done."
echo ""
echo "Start SAT EYE with:"
echo "  ./scripts/start_sateye.sh"
echo ""
echo "Then open http://127.0.0.1:5173"
echo "Upload satellite images locally — no internet required at runtime."
