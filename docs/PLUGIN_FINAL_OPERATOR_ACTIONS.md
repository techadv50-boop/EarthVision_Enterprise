# PLUGIN FINAL OPERATOR ACTIONS

Numbered in **execution order**. Do not skip ahead to production deploy.

---

### 1. Confirm RC tip and review PR #85

```bash
gh pr view 85 --repo techadv50-boop/EarthVision_Enterprise
git fetch origin cursor/sateye-plugin-rc-5d6d
git log -1 --oneline origin/cursor/sateye-plugin-rc-5d6d
```

UI: GitHub → PR #85 → review files + verification docs under `docs/PLUGIN_FINAL_*.md`.

---

### 2. Enable GitHub branch protection / rulesets (currently UNKNOWN — HTTP 403)

Repo **admin** (not this agent integration):

1. GitHub → **Settings → Rules → Rulesets** (or Branches → Branch protection).
2. Protect at least:
   - `cursor/scene-download-eye-5d6d` (locked baseline)
   - production/release target branch(es)
3. Require:
   - Pull request before merge
   - Required approvals (≥1)
   - **Require review from CODEOWNERS**
   - Required status checks (CI / Tool Protection workflows as configured)
   - Restrict who can bypass (admins ideally cannot bypass, or document exception)
4. Re-verify:

```bash
python3 scripts/tools/check_branch_protection_evidence.py
# expect overall PASS (not UNKNOWN/403)
```

---

### 3. Provision production publisher keys (out of band)

Follow `deployment/production/PROD_SIGNING_KEY_PROVISIONING.md`.

- Generate Ed25519 keypair **offline**
- Place **public** key only in production publishers JSON (from TEMPLATE)
- Store private key in HSM/secret manager — **never commit**

---

### 4. Issue production mTLS material

```bash
# Preview-only generator is NOT for production trust:
# python3 scripts/tools/generate_plugin_worker_mtls_certs.py
```

Use org PKI. Mount server/client/CA into worker + Host Shell. Set:

- `EV_PLUGIN_WORKER_TLS=1`
- `EV_PLUGIN_WORKER_URL=https://plugin_worker:8091`

Then retest unauthorized client (no cert / wrong cert → fail).

---

### 5. Inject unique worker auth token

In Dokploy / secret store (not git):

```bash
openssl rand -hex 24   # ≥32 hex chars
# set EV_PLUGIN_WORKER_AUTH_TOKEN=<value> for backend + plugin_worker
```

---

### 6. Record current production Host Shell identities (read-only)

On production host (authorized SSH/read-only):

```bash
docker ps --format 'table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}'
docker inspect <backend> <frontend> --format '{{.Name}} {{.Id}} {{.Image}} {{json .RepoDigests}}'
curl -fsS https://sateye.xdgen.com/health
```

Save outputs to the release ticket. **Do not recreate containers yet.**

---

### 7. Backup production volumes / DB

```bash
# Example — adapt to Dokploy volume names:
docker volume ls
# snapshot tool_packs + postgres per site backup standard
```

Confirm restore drill on non-production first.

---

### 8. Preview rehearsal with TLS=1 (optional but recommended)

```bash
export EV_PLUGIN_WORKER_AUTH_TOKEN="$(openssl rand -hex 24)"
export EV_PLUGIN_WORKER_TLS=1
export EV_PLUGIN_WORKER_URL=https://plugin_worker:8091
python3 scripts/tools/generate_plugin_worker_mtls_certs.py
docker compose -p sateye-preview-rc \
  -f docker-compose.preview.yml \
  -f tools/plugins/worker/compose.preview.yml \
  --env-file .env.preview up -d --build
# Re-run lifecycle + unauthorized mTLS client test; capture host IDs before/after
```

---

### 9. Obtain explicit written production deploy authorization

Product owner approval recorded in ticket. **Without this step: STOP.**

---

### 10. Production deploy (ONLY after steps 1–9)

Follow `docs/PLUGIN_RC_DEPLOYMENT_RUNBOOK.md` + Dokploy change ticket.

- Deploy Host Shell image digest that includes Plugin Manager
- Attach plugin_worker sidecar on internal network
- Mount publishers + tool_packs
- Smoke: health, 148 tools, True Color, Ship Detection, plugin install/activate without Host rebuild

---

### 11. Post-deploy verification

```bash
curl -fsS https://sateye.xdgen.com/health
# Admin UI → Plugin Manager health
# Confirm Host Shell container IDs unchanged across a plugin install cycle
```

---

### 12. If anything fails — execute rollback plan

See `docs/PLUGIN_FINAL_ROLLBACK_PLAN.md`. Do **not** delete production volumes.
