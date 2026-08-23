#!/usr/bin/env bash
# Start the Citation Assistant on a VPS with Cloudflare Tunnel → https://citation.xdgen.com
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — set CLOUDFLARE_TUNNEL_TOKEN and SECRET_KEY, then re-run."
  exit 1
fi
if ! grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.\+' .env; then
  echo "Set CLOUDFLARE_TUNNEL_TOKEN in .env (Cloudflare Zero Trust → Tunnels)."
  exit 1
fi
docker compose --profile tunnel up -d --build
echo "Stack is up. Point the tunnel hostname citation.xdgen.com at http://nginx:80"
echo "Login: citation@xdgen.com / pak123"
