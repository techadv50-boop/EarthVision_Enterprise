#!/usr/bin/env bash
# Idempotent dev-environment bootstrap for EarthVision Enterprise.
# Installs backend (Python) and frontend (Node) dependencies. Safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# System packages needed to create virtualenvs and build the geospatial/ML stack.
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-dev build-essential

# Backend: isolated virtualenv with pinned dependencies.
cd "$ROOT_DIR/backend"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip setuptools wheel
./.venv/bin/pip install -r requirements.txt

# Frontend: Node dependencies.
cd "$ROOT_DIR/frontend"
npm install

echo "EarthVision Enterprise dev environment ready."
