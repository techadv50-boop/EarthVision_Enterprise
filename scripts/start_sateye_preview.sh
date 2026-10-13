#!/usr/bin/env bash
# Start the isolated SATEYE preview stack. Never touches production compose.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.preview.yml}"
PROJECT="${COMPOSE_PROJECT_NAME:-sateye-preview}"
ENV_FILE="${ENV_FILE:-.env.preview}"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "missing $COMPOSE_FILE" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE — copy .env.preview.example to .env.preview first" >&2
  exit 1
fi

# Refuse accidental use of production project names / compose files.
case "$PROJECT" in
  sateye-fz2ic4|earthvision|sateye-prod|prod)
    echo "refusing production-like project name: $PROJECT" >&2
    exit 1
    ;;
esac
case "$COMPOSE_FILE" in
  docker-compose.yml|docker-compose.prod.yml)
    echo "refusing production compose file: $COMPOSE_FILE" >&2
    exit 1
    ;;
esac

echo "starting PREVIEW project=$PROJECT file=$COMPOSE_FILE"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

echo
echo "Preview edge (local):  http://127.0.0.1:8202/"
echo "Preview health:        http://127.0.0.1:8202/health"
echo "Preview API docs:      http://127.0.0.1:8202/docs"
echo "Public (after DNS):    https://sateye-preview.xdgen.com/"
echo
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps
