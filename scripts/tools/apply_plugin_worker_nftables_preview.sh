#!/usr/bin/env bash
# Preview-only helper: document/apply host nftables restrictions for plugin_worker bridge.
# Requires root on the preview host. Does NOT touch production Dokploy/sateye.xdgen.com.
#
# Kernel-enforced intent: plugin_worker_net is already Compose `internal: true`
# (no masquerade). This script adds an explicit drop for egress from the bridge
# to non-Docker destinations when NFT_BRIDGE is set.
set -euo pipefail

BRIDGE="${NFT_BRIDGE:-}"
if [[ -z "${BRIDGE}" ]]; then
  echo "INFO: Set NFT_BRIDGE=<docker_bridge_ifname> to apply rules."
  echo "INFO: Discover with: docker network inspect sateye_preview_plugin_worker_net"
  echo "STATUS: SKIPPED (no bridge provided) — Compose internal network remains primary control."
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: root required to apply nftables" >&2
  exit 1
fi

nft list table inet sateye_plugin_worker >/dev/null 2>&1 && nft delete table inet sateye_plugin_worker || true
nft -f - <<EOF
table inet sateye_plugin_worker {
  chain egress {
    type filter hook forward priority 0; policy accept;
    iifname "${BRIDGE}" oifname != "docker0" oifname != "${BRIDGE}" drop
  }
}
EOF
echo "OK: nftables table inet sateye_plugin_worker applied for ${BRIDGE}"
