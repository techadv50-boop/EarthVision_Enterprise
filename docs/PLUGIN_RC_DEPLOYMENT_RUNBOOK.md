# Plugin System — Preview / Future Production Deployment Runbook (RC)

**Scope:** Prepare overlays and procedures. **Does not** modify live `sateye.xdgen.com` or production Dokploy.

## Preview bring-up

```bash
# 1) Secrets (required — no compose defaults)
export EV_PLUGIN_WORKER_AUTH_TOKEN="$(openssl rand -hex 24)"

# 2) Optional mTLS
python3 scripts/tools/generate_plugin_worker_mtls_certs.py
export EV_PLUGIN_WORKER_TLS=1
export EV_PLUGIN_WORKER_URL=https://plugin_worker:8091

# 3) Start preview stack with worker overlay
docker compose -p sateye-preview \
  -f docker-compose.preview.yml \
  -f tools/plugins/worker/compose.preview.yml \
  --env-file .env.preview up -d --build

# 4) Optional kernel egress helper (root on preview host)
NFT_BRIDGE=<bridge> sudo -E scripts/tools/apply_plugin_worker_nftables_preview.sh
```

## Persistent volumes (inventory)

| Volume / path | Purpose | Backup |
|---------------|---------|--------|
| `sateye_preview_tool_packs` | Artifacts, registry, publishers, audit | Snapshot volume + copy `plugin_registry.json`, `publishers/`, `artifacts/`, `audit/` |
| Postgres / Redis (preview compose) | Host Shell data | Existing DB backup procedures |

## Immutable image digests

Record digests after build (preview):

```bash
docker compose -p sateye-preview images
docker image inspect <image> --format '{{index .RepoDigests 0}}'
```

Store digests in the release ticket. **Production image promote is BLOCKED** until separate approval.

## Health checks

- `GET /health` (API)  
- `GET http(s)://plugin_worker:8091/health` — isolation report  
- Admin Plugin Manager subsystem health badges  
- `scripts/tools/check_branch_protection_evidence.py` (expect UNKNOWN until admin enables protection)

## Migration plan (summary)

1. Deploy Host Shell build that includes Plugin Manager + worker client (this RC).  
2. Deploy plugin_worker sidecar on internal network with mTLS + auth token.  
3. Mount tool_packs volume RO into worker, RW into API for install.  
4. Provision production publishers JSON (template under `deployment/production/`).  
5. Activate plugins only after signature verify + canaries green.

## Production Compose / Dokploy

- Preview overlay: `tools/plugins/worker/compose.preview.yml`  
- Production overlay: **not applied** in this stage — prepare from preview pattern under operator change control  
- **Do not** edit live Dokploy services from this agent
