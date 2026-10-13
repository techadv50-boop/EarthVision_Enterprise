# Stage E1.10 — Production Deployment Preflight Report

**Date (UTC):** 2026-10-13  
**Scope authorized this stage:** Read-only production inventory (by operator) + deployment **preparation** only.  
**Not authorized / not performed:** Deploy SATEYE, compose/env edits, rebuild/restart, PR #76 merge into deploy tip, Tool Pack install/activate, Stage E2.

---

## 1. Executive result

### **NO-GO for Deploy SATEYE / Host Shell cutover**

| Gate | Status |
|------|--------|
| Operator package integrity (`104b39c`) | **PASS** |
| Inventory safety suite independent rerun | **PASS (65 / 0)** |
| Approved deploy tip `e3012ce` preserved | **PASS** |
| Exact-SHA CI + Tool Protection for `e3012ce` | **PASS** (code/API) |
| Admin reset default-off on tip workflow | **PASS** (code) |
| Tip image trust excludes preview-dev | **PASS** (code) |
| Imagery baseline `1e71b7a` ancestor of tip | **PASS** |
| **Sanitized live inventory from `zhzh`** | **MISSING — BLOCKER** |
| Live image digests / storage / runner online | **UNKNOWN — BLOCKER** |
| Live compose overlay Tool Pack readiness | **UNKNOWN — BLOCKER** |
| Live rollback image availability | **UNKNOWN — BLOCKER** |

**Primary blocker:** No sanitized operator inventory return is present in this environment. This agent has **no** `/opt/earthvision`, cannot resolve/SSH `zhzh`, and is **not** permitted to execute inventory itself. Owner authorized the **operator** to run inventory; until that scrubbed return arrives, production cutover evidence is incomplete → **STOP**.

Public non-mutating check only: `https://sateye.xdgen.com/health` → `healthy` / `postgresql`; `/api/v1/tools/runtime` → `404` (Host Shell tip not live — expected).

---

## 2. Package integrity verification

| Item | Value |
|------|--------|
| Inventory package commit | `104b39cf2a76be927d3847e8534257f397d0aebc` |
| Branch HEAD at verification | **identical** to package commit |
| Approved deploy tip | `e3012ce0a26e049d0af981d5994d0d829c3b647e` |
| Safety tests | `python3 scripts/tests/test_e19c_inventory_safety.py` → **pass=65 fail=0** |

Key file sha256 (at `104b39c`):

| File | sha256 |
|------|--------|
| `scripts/e19c_operator_inventory.sh` | `1769919338d8fce96a28a23c449256b6f3406661b5823b3bb7080fa11e6a81f9` |
| `scripts/e19c_inventory_lib.py` | `2c33a14bb48ceef96ca9d9f67844f1645799a0add66d54762cf23605e807c778` |
| `E19C_OPERATOR_INVENTORY_RUNBOOK.md` | `9cfa019e9b00c6bd786820607f1e6c64dd52a96928748a0ced1e16cbb5be1f75` |
| `E19C_RETURN_TEMPLATE.md` | `f29d784a5d1234b1c5f366781d3cf430838e6b6b051cac2b9570539cbadc946f` |

Artifact tarball (if used): `/opt/cursor/artifacts/e19d/EarthVision_E19D_Operator_Inventory_Package.tar.gz`

---

## 3. Authorized operator inventory (must still be executed / returned)

**Owner authorization:** Operator may run the verified E1.9D read-only inventory on `zhzh` using package `104b39c`.

### Target identity (STOP if mismatch)

| Attribute | Expected |
|-----------|----------|
| Host | `zhzh` |
| App dir | `/opt/earthvision` |
| Compose project | `sateye-fz2ic4` |
| URL | `https://sateye.xdgen.com` |
| Required services in project | backend, frontend, proxy (`nginx`/`caddy`/`traefik`/`proxy`/`edge`) |

### Exact commands (side directory — never write into `/opt/earthvision`)

```bash
git fetch origin cursor/sateye-e19c-inventory-runbook-5d6d
git checkout 104b39cf2a76be927d3847e8534257f397d0aebc
# or extract the E19D operator tarball

export APP_DIR=/opt/earthvision
export OUT_DIR="/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ)"
export EXPECTED_HOST=zhzh
export EXPECTED_PROJECT=sateye-fz2ic4
# Do NOT set SKIP_HOST_CHECK

bash scripts/e19c_operator_inventory.sh
cat "$OUT_DIR/00_return_summary.txt"
cat "$OUT_DIR/15_manifest.txt"
# Share ONLY if share_safe=yes — use E19C_RETURN_TEMPLATE.md
```

### Required return fields (sanitized)

`identity_result`, `live_branch`, `live_commit`, `baseline_1e71b7a_ancestor`, backend/frontend/proxy `image_id` + digests, volume names + mount destinations, redacted/allowlisted compose structure, `runner_status`, `actions_runs_api`, `ev_pack_env_names_present`, `env_sha256`, `compose_sha256`, `share_safe=yes`, `changes_made=none`.

---

## 4. Code-side evidence (does **not** replace live inventory)

### 4.1 Exact-SHA CI / Tool Protection (`e3012ce`)

Independent gate dry-run:

```
OK: all required workflows succeeded for e3012ce0a26e049d0af981d5994d0d829c3b647e
ci.yml success; tool-protection.yml success
```

Deploy workflow (tip): fail-closed `deploy_verify_ci_gate.sh` + `DEPLOY_EXPECTED_SHA` post-merge check; runner labels `[self-hosted, Linux, X64, sateye-live]`.  
**Live runner online status:** still **UNKNOWN** until inventory §13.

### 4.2 Administrator reset protection

- `RESET_ADMIN_PASSWORD` defaults to **0**
- Workflow sets reset only if `admin_reset_confirm=reset-admin` **and** `confirm=deploy`
- Ordinary Host Shell deploy must leave `admin_reset_confirm` **empty**

### 4.3 Production publisher trust (tip defaults)

| Source | preview-dev? | Notes |
|--------|--------------|-------|
| `approved_publishers.image_default.json` | **Absent**; no enabled publishers | Fail-closed bake-in |
| Dockerfile `EV_PACK_TRUST_PROFILE` | `production` | Filters preview publishers |
| Production TEMPLATE | placeholder id, `enabled:false` | No private keys |
| Preview publishers file | preview-only | Must not be mounted in prod |

**Live** `EV_PACK_*` / volume publishers: **UNKNOWN** until inventory. Host Shell with **builtin** pin does not load pack plugins; volume overlay still required before any future activate.

### 4.4 Imagery baseline

- Tag `sateye-baseline-20261012-1e71b7a` → `1e71b7a…`
- `1e71b7a` **is ancestor** of approved tip `e3012ce`
- Deploying `e3012ce` therefore **retains** imagery fixes in git history
- Live tree ancestry still must be confirmed by inventory (`baseline_1e71b7a_ancestor`)

### 4.5 Tool shell preservation

Manifest at tip: **148 unique tool IDs** (`counts.unique_ids=148`); PoC `true_color`; canary `ship_detection`.  
Git `tools/runtime_pins.json`: `true_color.mode=builtin`.  
Deploy must leave live pin **builtin** (volume pins if present must not flip to pack without separate activation approval).

### 4.6 Persistent data preservation design (deploy script)

`deploy_sateye_live.sh` (tip):

- Preserves/restores live `docker-compose.yml` + `backend/requirements.txt` overlays
- Never `docker compose down -v`
- Never overwrites `.env` from git
- PostgreSQL named volume and bind mounts intended to survive recreate

**Live confirmation** of pgdata / imagery / uploads / cache / logs mounts: **requires inventory**.

---

## 5. Proposed Host Shell deployment plan (DO NOT EXECUTE YET)

Execute only after: (A) sanitized inventory PASS, (B) owner explicit Deploy authorization, (C) abort conditions understood.

### 5.1 Preconditions checklist

1. Inventory `identity_result=PASS` on `zhzh` / `/opt/earthvision` / `sateye-fz2ic4`
2. Record **prior** live commit + backend/frontend image digests (rollback refs)
3. Confirm pgdata + imagery/uploads/cache/logs mounts present; **no** `down -v` planned
4. `baseline_1e71b7a_ancestor=yes` on live **or** accept tip deploy restores fixes via `e3012ce`
5. `sateye-live` runner **online**; Actions runs API readable for tip SHA
6. Live overlay: either already has Tool Pack keys **or** ops will merge `compose.overlay.tool_packs.proposed.yml` **additively** into the **live** overlay (and preserve copy) **before/during** cutover — deploy restores overlay after ff-merge
7. Seed `tool_packs` volume with **builtin** pins only; production publishers file without preview-dev (enabled false OK for Host Shell)
8. `admin_reset_confirm` left **empty**
9. Deploy SHA locked to branch tip that is **`e3012ce`** (do not merge PR #76 into deploy tip unless owner re-stamps tip)

### 5.2 Exact Deploy SATEYE procedure (when later authorized)

1. Confirm GitHub Actions → Deploy SATEYE → branch `cursor/scene-download-eye-5d6d` resolves to SHA **`e3012ce0a26e049d0af981d5994d0d829c3b647e`** (if tip moved, **STOP** and re-authorize).
2. Workflow inputs:
   - `confirm` = `deploy`
   - `admin_reset_confirm` = *(empty)*
3. CI gate must pass for that exact SHA (automatic on tip workflow).
4. Live script: preserve overlays → ff-merge → restore overlays → rebuild/recreate **without** `-v` → health checks.
5. Post-deploy verify:
   - Local + public `/health` OK
   - Homepage OK
   - Login OK
   - `GET /api/v1/tools/runtime` → `true_color.mode == builtin`
   - True Color composite coherent (builtin)
   - ship_detection / catalog still available
   - Record **new** image digests; retain priors

### 5.3 Abort conditions (stop before or during deploy)

- Wrong host/project/app dir
- Live dirty tree outside allowlist
- Overlay preserve/restore failure
- `.env` checksum changes during merge
- CI gate fail / wrong SHA after merge
- Health or homepage failure after recreate
- Pin observed `mode=pack` without activation approval
- Any `docker compose down -v` or volume wipe request
- Runner offline / cannot verify SHA

### 5.4 Rollback procedure (do not execute now)

1. Keep prior digests from inventory `06_images.txt` / `07_rollback.txt`
2. Restore preserved compose/requirements from `/home/zh/earthvision-deploy-preserve` (or inventory-noted preserve dir)
3. Re-tag/recreate from **prior** backend/frontend image IDs (must still exist locally — inventory must confirm)
4. Re-check `/health` + homepage + login
5. Do **not** use pack rollback unless a pack was activated (out of scope for Host Shell)

### 5.5 Smoke tests (post-deploy)

| # | Test | Expect |
|---|------|--------|
| S1 | `GET /health` local+public | healthy + postgresql |
| S2 | Homepage | 200 SAT EYE |
| S3 | Auth login | success |
| S4 | `/api/v1/tools/runtime` | true_color builtin |
| S5 | True Color overlay | coherent builtin render |
| S6 | Catalog / ship_detection | available |

---

## 6. Inventory-dependent fields (blank until operator return)

Paste sanitized values here when received:

```text
live_commit=
live_branch=
baseline_1e71b7a_ancestor=
backend_image_id=
backend_repo_digest=
frontend_image_id=
frontend_repo_digest=
proxy_image_id=
named_volumes=
bind_mount_destinations=
runner_status=
actions_runs_api=
ev_pack_env_names_present=
env_sha256=
compose_sha256=
share_safe=
```

---

## 7. Updated GO / NO-GO

| Decision | Status |
|----------|--------|
| Operator may run E1.9D inventory on `zhzh` | **Authorized by owner (this stage)** |
| Agent / automation may SSH or invent inventory | **NO** |
| Deploy SATEYE / Host Shell cutover now | **NO-GO — awaiting sanitized inventory + separate deploy approval** |
| Merge PR #76 into deploy tip | **NO** (would move tip past `e3012ce` unless re-stamped) |
| Tool Pack install/activate | **NO-GO** |
| Stage E2 | **NO-GO** |

### Path to GO

1. Operator returns scrubbed inventory (`share_safe=yes`).
2. Preflight reviewer fills §6; clears storage/runner/digest/trust live checks.
3. Owner issues **explicit Deploy SATEYE authorization** for Host Shell only (builtin pin).
4. Execute §5.2 with abort/rollback armed.

---

**STOP. Awaiting sanitized inventory return and explicit deployment authorization.**
