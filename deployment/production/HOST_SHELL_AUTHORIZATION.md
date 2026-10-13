# Stage E1.8 — Production Authorization Package

**Status:** Review package only. **No production changes applied.**  
**Date:** 2026-10-13  
**Branch:** `cursor/scene-download-eye-5d6d`  
**Proposed Host Shell deploy commit:** `3e6be12096d068e83e18057f07cedf3c8bf5358e` (`3e6be12`)  
**Imagery / approved-tool baseline tag:** `sateye-baseline-20261012-1e71b7a` → `1e71b7a` (**ancestor of tip**)

---

## 1. GO / NO-GO recommendation

### **NO-GO for immediate production Deploy SATEYE**

Host Shell code is ready in git and validated in isolated preview, but the following blockers must be cleared before GO:

| ID | Blocker | Severity | Resolution |
|----|---------|----------|------------|
| B-CI | Deploy SATEYE does **not** require CI / Tool Protection to be green | High | Manual PASS on checklist B3–B5, or add an explicit workflow gate before future GO |
| B-TRUST | Backend image default `EV_PACK_PUBLISHERS` bakes **preview-dev** public key | High | Live overlay must set `EV_PACK_PUBLISHERS=/data/tool_packs/publishers/approved_publishers.json` with production TEMPLATE (preview-dev absent) |
| B-OVERLAY | Live `docker-compose.yml` is a **server overlay**; Tool Pack volume not merged yet | High | Ops merges `compose.overlay.tool_packs.proposed.yml` into preserve-backed live compose **before** or as part of approved cutover |
| B-DIGESTS | Current live image digests unknown to this agent (no prod access) | High | Ops captures prior backend/frontend digests + live git SHA before deploy (checklist C1–C2) |
| B-KEYS | No production Ed25519 publisher provisioned | Medium for Host Shell (builtin only); **High** before any activate | Generate offline; public key only on volume; private key in secrets manager — never git |
| B-ADMIN | Deploy workflow sets `RESET_ADMIN_PASSWORD=1` | Medium / ops | Confirm intentional password reset side effect |

**Path to GO:** All PREFLIGHT checklist sections A–E PASS, then explicit owner approval to run Deploy SATEYE for Host Shell only (pin remains builtin).

---

## 2. Exact proposed production changes (reviewable; not applied)

| Artifact | Purpose |
|----------|---------|
| `deployment/production/compose.overlay.tool_packs.proposed.yml` | Additive live compose merge (volume + env) |
| `deployment/production/runtime_pins.builtin.proposed.json` | Seed pin file for `tool_packs` volume |
| `deployment/production/approved_publishers.production.TEMPLATE.json` | Prod trust allowlist template (no private keys) |
| `deployment/production/PREFLIGHT_CHECKLIST.md` | PASS/FAIL gate sheet |
| This document | Authorization package |

### What reaches production from tip `3e6be12` vs baseline `1e71b7a`

**4 commits** after imagery baseline:

1. `6c1956c` — Stage C manifest + CI guards  
2. `47ab90a` — E0/E1 Host SDK + true_color packs  
3. `1810247` — E1.5 pin reliability  
4. `3e6be12` — E1.7 volume paths, signed install/activate, preview wiring  

**58 files**, ~7682 insertions (mostly `tools/manifest.json` + tests/docs/packs).  

**Unrelated to Tool Packs?** Essentially none outside protection/docs — no ship_detection algorithm rewrite in this range; imagery fixes already in `1e71b7a`. Frontend change is thin `hostSdk.ts` façade helper only.

**Dockerfile.backend delta (will rebuild backend image):**

- COPY publishers JSON + manifest into image  
- ENV defaults for `EV_*` tool pack paths  
- mkdir `/data/tool_packs/...`  

**Not changed by tip:** repo `docker-compose.yml` (dev), `deployment/nginx.conf`, deploy branch lock, Deploy SATEYE workflow target branch.

**Live overlay:** remains authoritative for compose; must be **manually** augmented with Tool Pack volume/env (proposed file). Deploy script **restores** the live overlay after git merge — so the merge must already include Tool Pack keys **in the live overlay file** before/during cutover, or they will be wiped back to the pre-merge overlay snapshot.

**Critical ops note:** `deploy_sateye_live.sh` preserves then restores `docker-compose.yml`. If Tool Pack keys are only in git `docker-compose.yml` / snippet but **not** in the live overlay that gets restored, the rebuilt containers will **lose** the volume mount after deploy. Therefore: edit the **live** overlay (and its preserve copy) to include Tool Pack keys as part of the approved cutover procedure.

---

## 3. How Tool Pack config is introduced without overwriting production data

| Asset | Mechanism |
|-------|-----------|
| `.env` | Never from git; checksum enforced across merge |
| `docker-compose.yml` | Server overlay preserved → restored after ff-merge |
| `backend/requirements.txt` | Same overlay preserve/restore |
| PostgreSQL `pgdata` | Named volume; never `down -v` |
| uploads / imagery / cache / logs | Bind mounts preserved |
| **New** `tool_packs_data` | Additive named volume only |

Pin source of truth in production = **`EV_RUNTIME_PINS` on `tool_packs` volume`**, not git `tools/runtime_pins.json` (avoids dirty-tree / merge overwrite of pins).

---

## 4. Signing & trust (production ≠ preview)

| | Preview | Production (required) |
|--|---------|------------------------|
| Publisher id | `preview-dev` | Distinct id from TEMPLATE |
| Public key location | Image bake + preview compose | **Volume** `/data/tool_packs/publishers/approved_publishers.json` |
| Private key | Local/CI secret only; gitignored | Secrets manager only — **never commit** |
| Artifact signatures in git | Signed with preview-dev for dev/preview | Must be **re-signed** by prod publisher before prod install |
| `EV_PACK_REQUIRE_SIGNATURE` | `1` | `1` |

Host Shell with builtin does not load pack plugins. Before any future activate, prod must not accept preview-dev (override publishers path).

---

## 5. Auto-activation verification

| Path | Activates pack? |
|------|-----------------|
| Deploy SATEYE / `deploy_sateye_live.sh` | **No** |
| Container start / uvicorn | **No** (may create builtin pin via `ensure_default_pins`) |
| `pack_install.py` | **No** (install only) |
| `pack_activate.py` | **Yes** — requires `--confirm activate` |
| HTTP API | Read-only introspection; **no** promote endpoint |

First Host Shell production deploy **must** leave `true_color` in **builtin**.

---

## 6. CI vs production workflow

| Workflow | On push/PR | Gates Deploy SATEYE? |
|----------|------------|----------------------|
| `ci.yml` | Yes | **No** (manual verify required) |
| `tool-protection.yml` (E1.5+E1.7) | Yes | **No** (manual verify required) |
| `deploy-sateye.yml` | Manual `confirm=deploy` only | Self-gated by confirm string only |

**Cannot be bypassed by deploy workflow:** CI is independent — green status does not block a mistaken deploy unless humans follow checklist B5. This remains a **process** control until a code change adds `workflow_run`/status checks (out of E1.8 apply scope).

---

## 7. Host Shell deployment procedure (proposed; not executed)

### Pre
1. Complete PREFLIGHT checklist → all PASS  
2. Capture live digests/SHA into ops notes  
3. Merge Tool Pack keys into **live** compose overlay; seed volume with builtin pins + prod publishers TEMPLATE  
4. Confirm branch `cursor/scene-download-eye-5d6d` @ approved SHA  

### Deploy
5. GitHub Actions → **Deploy SATEYE** → `confirm=deploy`  
6. Script: preserve overlays → ff-only merge → restore overlays → `docker compose build backend frontend` → recreate backend/frontend/nginx (**no** `-v`)  
7. Health + homepage + login + `tools/runtime` pin == builtin  

### Explicitly do **not**
- Run `pack_install` / `pack_activate`  
- Stage E2  
- `docker compose down -v`  

---

## 8. Host Shell rollback plan

### Inputs to capture **before** deploy (ops)

```text
PRIOR_GIT_SHA=________
PRIOR_BACKEND_IMAGE_ID=________
PRIOR_FRONTEND_IMAGE_ID=________
COMPOSE_SHA256=________
REQUIREMENTS_SHA256=________
ENV_SHA256=________   # fingerprint only
```

Preserve dir (existing): `/home/zh/earthvision-deploy-preserve/`

### Rollback (Host Shell / app images) — conceptual commands for ops

1. Do **not** wipe volumes.  
2. Restore git tree to `PRIOR_GIT_SHA` on locked branch via controlled ff/checkout policy used by ops (or redeploy known-good tip).  
3. Ensure live compose overlay from preserve is intact.  
4. `docker compose build` / `up -d --force-recreate backend frontend nginx` at prior SHA, **or** retag/run prior image IDs if retained.  
5. Verify health, homepage, login, true_color builtin, ship canary.  
6. Confirm `.env` fingerprint unchanged.

### Pack activation rollback (future; separate)

```bash
python3 scripts/tools/pack_rollback.py --tool true_color --to builtin \
  --actor "$USER" --confirm rollback
```

See `docs/TOOL_PACK_E17_ROLLBACK.md`.

---

## 9. Future Tool Pack activation procedure (separate from Host Shell)

**Only after** Host Shell is healthy on builtin and owner approves activation.

1. Provision production publisher (public on volume; private in secrets).  
2. Build/sign artifact with **production** key (do not reuse preview signatures from git).  
3. `pack_install.py … --confirm install` → verify digest + signature → immutable publish.  
4. Health / dry-run render still on builtin.  
5. **Separate approval** → `pack_activate.py … --confirm activate`.  
6. Multi-request `/tools/runtime` + composite checks across workers.  
7. Record audit JSONL.  
8. Rollback: `pack_rollback.py --to builtin|--to <prior> --confirm rollback`.

Install never activates. Deploy never activates.

---

## 10. Remaining risks (even after GO)

- In-process plugin execution = backend OS privileges  
- Brief multi-worker pin observation window during future activates (E1.5 mitigations)  
- Live overlay human-merge error could drop Tool Pack volume or other mounts  
- Admin password reset on each Deploy SATEYE  
- Cloudflare/edge 502 if nginx not recreated (script already force-recreates nginx)

---

## 11. Final Git status for this package

Authorization package files are committed on `cursor/scene-download-eye-5d6d` under `deployment/production/`.  
**No production server modifications.** **No Deploy SATEYE.** **No E2.**

---

## STOP

Await **explicit approval** before any production Host Shell deployment or Tool Pack install/activation.
