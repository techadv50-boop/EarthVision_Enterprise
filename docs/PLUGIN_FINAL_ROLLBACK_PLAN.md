# PLUGIN FINAL ROLLBACK PLAN

**Scope:** Plugin system RC. Preserves Host Shell and legacy 148 tools.  
**Production changes:** none performed by the verification agent.

---

## Tier A — Plugin-only rollback (no Host Shell restart)

**When:** Bad plugin version, bad UI, failed analysis, suspect pack.

1. Admin → Plugin Manager → select plugin  
2. **Rollback** to previous known-good version **or** **Disable**  
3. Confirm:
   - FE slot empty / previous UI
   - `POST /api/v1/plugins/{id}/synthetic` fails if disabled
   - Audit shows `rollback` or `disable` with `ok=true`
4. Host Shell containers must **remain the same IDs** (install/activate/rollback mutate `tool_packs` only)

API equivalent:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"confirm":"rollback","to":"1.0.0"}' \
  "$API/api/v1/admin/plugins/demo_hello/rollback"

curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"confirm":"disable"}' \
  "$API/api/v1/admin/plugins/demo_hello/disable"
```

---

## Tier B — Worker outage / compromise

1. Leave `EV_PLUGIN_WORKER_REQUIRED=1` (fail closed for plugin execution)  
2. Legacy tools / True Color / Ship Detection continue on Host Shell paths  
3. Restore worker from last known-good **image digest**  
4. Rotate `EV_PLUGIN_WORKER_AUTH_TOKEN` if leakage suspected  
5. If mTLS CA compromised: re-issue certs; do not reuse preview CA in production  

---

## Tier C — Host Shell application rollback (infrastructure)

1. Dokploy/operator redeploys previous Host Shell image digest only  
2. Retain `tool_packs` volume (do **not** delete)  
3. Re-validate active pins / signatures after Host comes up  
4. Requires separate production authorization  

---

## Tier D — Compromised publisher key

1. Disable publisher id in approved publishers JSON  
2. `scripts/tools/rotate_publisher_key.py` (or manual JSON edit in secret mount)  
3. Re-sign future packs; already-installed digests remain until replaced  
4. Audit the install/activate history for that publisher  

---

## Tier E — Full abort of plugin feature flag (if needed)

1. Disable all active plugins  
2. Stop plugin_worker service  
3. Keep Host Shell serving core product  
4. Do **not** wipe production DB or imagery volumes  

---

## Verification after any rollback

- `GET /health` → healthy  
- True Color + Ship Detection smoke  
- Plugin admin health shows expected worker/plugin state  
- Audit log entries present without secrets  
