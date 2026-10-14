# PLUGIN FINAL PRODUCTION CHECKLIST

**Production URL:** https://sateye.xdgen.com  
**Access mode this run:** read-only HTTP health only — **no Dokploy writes, no SSH assume, no volume mutation.**

| Item | Status | Evidence | Operator verification command / action |
|------|--------|----------|----------------------------------------|
| Production Compose / Dokploy config present in repo | **PASS** (proposed) | `deployment/production/compose.overlay.tool_packs.proposed.yml`, runbooks | Review proposed overlay; do **not** apply without approval |
| Immutable container image references in prod | **UNKNOWN** | Not readable without host access | On prod host: `docker inspect <svc> --format '{{.Image}} {{index .RepoDigests 0}}'` |
| Required env vars / secrets | **BLOCKED** | Must be unique per env; not in git | Set `EV_PLUGIN_WORKER_AUTH_TOKEN`, DB, `SECRET_KEY` via Dokploy secrets |
| Publisher public-key configuration | **BLOCKED** | Template only | Complete `approved_publishers.production.TEMPLATE.json` → mounted path; see PROD_SIGNING_KEY_PROVISIONING.md |
| mTLS certificate requirements | **BLOCKED** | Preview CA only in repo | Issue org PKI certs; set `EV_PLUGIN_WORKER_TLS=1` + CA/client/server mounts |
| Network / firewall rules | **UNKNOWN** | Compose internal net verified in preview only | Confirm prod worker not published; nftables/security groups deny egress |
| Persistent storage / volumes | **UNKNOWN** | Repo documents `tool_packs` volume | `docker volume ls \| rg tool_packs`; confirm backup target |
| Database migration requirements | **PASS** (none for plugins) | Plugin state is volume/registry JSON, not Alembic | Confirm no pending Host Shell migrations separately |
| Backup / restore procedure | **BLOCKED** | Documented; drill not executed | Snapshot `tool_packs` + DB; restore drill on non-prod |
| Rollback procedure | **PASS** (documented) | `PLUGIN_FINAL_ROLLBACK_PLAN.md` + RC rollback runbook | Operator rehearses plugin rollback in preview |
| Health checks / failure recovery | **PASS** (code) / **UNKNOWN** (prod) | Preview `/health` 200; prod `/health` 200 read-only | `curl -fsS https://sateye.xdgen.com/health` |
| Compatibility with existing prod services | **UNKNOWN** | No live plugin sidecar observed from outside | After approved deploy: verify legacy tools + true_color + ship detection smoke |
| Prod HTTP surface untouched this run | **PASS** | GET `/health` and `/` only | `/opt/cursor/artifacts/final_prod_health.json` |

## Production readiness decision

**NO-GO** for production merge/deploy until operator actions in `PLUGIN_FINAL_OPERATOR_ACTIONS.md` are completed and separately authorized.
