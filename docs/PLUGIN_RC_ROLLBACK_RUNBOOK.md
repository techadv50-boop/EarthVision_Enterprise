# Plugin System — Rollback Runbook (RC)

## A. Rollback a plugin (no Host Shell restart)

1. Admin → Plugin Manager → select plugin  
2. **Rollback → previous version** or **Rollback → inactive**  
3. Confirm FE slot clears or reverts; worker rejects non-active pins  
4. Verify audit event `rollback` ok=true  

This does **not** rebuild or restart Host Shell images.

## B. Disable a misbehaving plugin

1. **Disable** in Plugin Manager  
2. Confirm `GET /plugins/{id}/frontend` fails closed  
3. Confirm worker `/v1/execute` returns 403 for that pin  

## C. Worker outage

1. If `EV_PLUGIN_WORKER_REQUIRED=1`, Host Shell refuses plugin execution (fail closed)  
2. Legacy 148 tools / True Color / Ship Detection continue (separate paths)  
3. Restore worker container from last known good image digest  

## D. Host Shell application rollback (infrastructure)

1. Redeploy previous **Host Shell** image digest only (Dokploy/operator)  
2. tool_packs volume retains installed plugins; re-validate active pins  
3. **Not performed by this RC agent** — production remains untouched  

## E. Compromised publisher key

1. `scripts/tools/rotate_publisher_key.py --disable-id <old> --add-id <new> ...`  
2. Re-sign future packs with new key  
3. Already-installed digests remain; new installs require new signatures  
