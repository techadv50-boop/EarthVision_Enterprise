# Production Host Shell Preflight Checklist (E1.8)

**Deploy tip (proposed):** `origin/cursor/scene-download-eye-5d6d` (E1.7 runtime `3e6be12` + E1.8 package)  
**Branch:** `cursor/scene-download-eye-5d6d`  
**Baseline preserved:** `sateye-baseline-20261012-1e71b7a` (`1e71b7a` imagery fixes = ancestor)

Mark each item PASS / FAIL. Any FAIL = **STOP**.

## A. Authority & scope

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| A1 | Explicit written approval for Host Shell Deploy SATEYE only (not pack activate) | |
| A2 | Stage E2 / additional tool migration explicitly NOT authorized | |
| A3 | Deploy branch confirmed `cursor/scene-download-eye-5d6d` | |

## B. Git & CI

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| B1 | Tip is `cursor/scene-download-eye-5d6d` and contains `3e6be12` (E1.7) + E1.8 `deployment/production/` package | |
| B2 | `git merge-base --is-ancestor 1e71b7a HEAD` → yes (imagery fixes retained) | |
| B3 | GitHub **CI** workflow green on tip | |
| B4 | GitHub **Tool Protection** workflow green on tip (includes E1.5 + E1.7) | |
| B5 | Operator manually verified B3+B4 before clicking Deploy (Deploy SATEYE does **not** auto-gate on CI) | |

## C. Live server backups (ops on zhzh — read-only capture before change)

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| C1 | Record live `git rev-parse HEAD` and short SHA | |
| C2 | Record `docker images` / `docker inspect` IDs for backend + frontend (**prior digests**) | |
| C3 | Preserve copy of live `docker-compose.yml` + `backend/requirements.txt` checksums | |
| C4 | Confirm `.env` present; record size+sha256 only (never print secrets) | |
| C5 | Confirm `pgdata` volume name; **no** plan to run `down -v` | |
| C6 | Confirm uploads/imagery/cache/logs bind mounts present | |

## D. Tool Pack volume & trust (before/at cutover)

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| D1 | Live compose overlay merged per `compose.overlay.tool_packs.proposed.yml` (additive only) | |
| D2 | `tool_packs_data` volume created empty or seeded with **builtin** pins only | |
| D3 | Production publisher file installed at `/data/tool_packs/publishers/approved_publishers.json` from TEMPLATE (preview-dev **absent** / disabled) | |
| D4 | `EV_PACK_PUBLISHERS` points at volume path (overrides image-baked preview allowlist) | |
| D5 | No pack artifacts installed yet OR artifacts present but pin remains `builtin` | |
| D6 | No production private keys in git or image | |

## E. Non-activation guarantees

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| E1 | `tools/runtime_pins.json` in git remains `builtin` (informational; live pin is volume) | |
| E2 | Deploy SATEYE / `deploy_sateye_live.sh` contains no `pack_activate` / pin flip | |
| E3 | First boot `ensure_default_pins()` yields builtin if pin file missing | |
| E4 | Operator will **not** run `pack_activate.py` during Host Shell window | |

## F. STOP conditions (abort before or during deploy)

- Wrong branch or unexpected dirty paths outside allowlist
- Preservation of compose/requirements fails
- `.env` checksum changes during merge
- Health or homepage checks fail after recreate
- Pin observed as `mode=pack` after Host Shell cutover without separate activation approval
- Any command involving `docker compose down -v` or production volume wipe

## G. Post-deploy PASS criteria (Host Shell only)

| # | Criterion | PASS/FAIL |
|---|-----------|-----------|
| G1 | `/health` and homepage OK (local + public) | |
| G2 | Login works | |
| G3 | `GET /api/v1/tools/runtime` → `true_color.mode == builtin` | |
| G4 | True Color composite returns coherent overlay (builtin path) | |
| G5 | ship_detection / catalog still available (148-tool shell) | |
| G6 | New backend/frontend image digests recorded; prior digests archived for rollback | |
