# Stage E1.9A Status — Production Deployment Safety Hardening (dev only)

**Date:** 2026-10-13  
**Branch:** `cursor/scene-download-eye-5d6d`  
**Scope:** Code/docs/tests only — **no** production access, **no** Deploy SATEYE.

## Blockers resolved in code

| ID | Resolution |
|----|------------|
| **B-CI** | `scripts/deploy_verify_ci_gate.sh` + Deploy workflow step; fail-closed for missing/pending/failed/cancelled/wrong SHA; `DEPLOY_EXPECTED_SHA` post-merge check |
| **B-ADMIN** | `RESET_ADMIN_PASSWORD` default **0**; workflow requires `admin_reset_confirm=reset-admin`; maintenance doc |
| **B-TRUST** | Image default empty allowlist; `EV_PACK_TRUST_PROFILE=production` filters preview-dev; preview compose uses preview publishers only |
| **B-OVERLAY (code)** | `scripts/deploy_merge_compose_overlay.py` additive merge + fixtures/tests; backup required to overwrite live |
| **B-DIGESTS (code)** | `scripts/deploy_capture_preflight.sh` read-only capture; refuses `/opt/earthvision` unless explicitly allowed |
| **B-KEYS (prep)** | `PROD_SIGNING_KEY_PROVISIONING.md` — no private keys generated/committed |

## Still requiring production verification (before GO)

| ID | Remaining ops work |
|----|--------------------|
| B-OVERLAY | Apply merge on live overlay under change control (script ready; not executed) |
| B-DIGESTS | Run preflight on live with `DEPLOY_PREFLIGHT_ALLOW_PROD=1` after authorization |
| B-KEYS | Provision real production publisher public key on volume |
| B-CI (live) | Confirm GitHub Actions API visibility from `sateye-live` runner token |
| Cutover | Explicit approval for Host Shell Deploy SATEYE with pin left **builtin** |

## Updated GO/NO-GO

**NO-GO for production deploy** until remaining production verification items above are completed and owner approves Host Shell cutover.

Code-level E1.8 blockers that blocked GO are addressed in-repo; live application of overlay/preflight/keys remains ops-gated.
