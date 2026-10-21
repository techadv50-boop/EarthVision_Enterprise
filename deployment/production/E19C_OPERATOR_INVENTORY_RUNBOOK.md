# Stage E1.9C-R2 — Operator Read-Only Production Inventory Runbook

**Status:** PREPARATION / SAFETY-CORRECTED (R2 field validation + archive allowlist) — execute on production only after explicit owner approval.  
**Date:** 2026-10-13  
**Approved deploy tip (unchanged):** `cursor/scene-download-eye-5d6d` @ `e3012ce0a26e049d0af981d5994d0d829c3b647e`  
**Helper:** `scripts/e19c_operator_inventory.sh` + `scripts/e19c_inventory_lib.py`

| Role | Action |
|------|--------|
| Development agent | Prepared/corrected this runbook; **must not** access production |
| Authorized operator | Runs inventory **only after owner authorization** |
| Owner | Reviews sanitized results before any production change |

---

## 0. Expectations (STOP if mismatch)

| Attribute | Expected |
|-----------|----------|
| Hostname | `zhzh` |
| Application directory | `/opt/earthvision` |
| Compose project | `sateye-fz2ic4` |
| Required containers **in that project** | `backend`, `frontend`, and proxy (`nginx`/`caddy`/`traefik`/`proxy`/`edge`) |
| Public URL | `https://sateye.xdgen.com` |
| Deploy runner label | `sateye-live` |
| Imagery baseline | `1e71b7a…` (`sateye-baseline-20261012-1e71b7a`) |
| Approved Host Shell tip | `e3012ce…` (not necessarily live) |

**Global STOP:** Wrong hostname, missing `/opt/earthvision`, or missing required services **labeled** `com.docker.compose.project=sateye-fz2ic4` → stop immediately. Presence of `sateye-fz2ic4` somewhere on the host while backend/frontend/proxy actually run under another project (e.g. preview) is **not** a pass.

**`SKIP_HOST_CHECK` is not supported.** If set, the helper exits with an error before any inventory.

---

## 1. Redaction / allowlist rules (mandatory)

| Collect | Do not collect |
|---------|----------------|
| Service names, container names, status | Environment **values** |
| Env **names** only (`NAME=<redacted>`) | Passwords, tokens, private keys |
| Named volume names; mount **destinations** | Database/redis connection strings |
| Image IDs / RepoDigests / RepoTags | `.env` contents (size+sha256 only) |
| Git branch/SHA; compose sha256 | Auth headers, cookies, user imagery/DB rows |
| Health HTTP code + allowlisted JSON fields (`status`,`version`,`environment`,`database`) | Full health response bodies on disk |
| Runner name/status/labels; Actions conclusion/status | Raw `gh auth status`, unfiltered API error bodies |

**Never run** `docker compose config` for capture (it expands secrets). Structural inventory is parsed from the live `docker-compose.yml` **file** with values discarded.

**Field validation (R2):** Every externally sourced value is type/format-checked (length, charset, allowlists). Credential-like strings in metadata (e.g. `user:pass@`, `ghp_`, `?token=`) become `UNKNOWN`/`FAIL` before write — not deferred solely to the final scanner.

**Share rule:** Summary + manifest must be complete first. Archive includes **only** `APPROVED_ARCHIVE_FILES`, mode `0600`. If the secret scanner fails/hits, or archive member verification fails → **do not share**.

---

## 2. Forbidden commands (entire session)

- `docker compose up|down|pull|build|restart|stop|start|create|rm`
- `docker compose config` (secret expansion)
- Mutating `docker exec` / SQL / file writes into volumes
- `git checkout|reset|pull|merge|push|clean`
- Editing compose, `.env`, credentials, networks, volumes
- `gh workflow run` / any Deploy SATEYE `workflow_dispatch`
- Setting `SKIP_HOST_CHECK`

---

## 3. Output directory rules

```bash
# Safety: private operator-controlled directory OUTSIDE the app tree.
# Helper resolves symlinks, requires absolute path under /tmp, /var/tmp, or $HOME,
# creates mode 0700, and refuses paths inside APP_DIR.
set -euo pipefail
OUT="/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ)"
# Do NOT place OUT under /opt/earthvision
```

---

## 4. Recommended execution (after owner approval)

Use a **side copy** of the E1.9C-R1 scripts (this PR branch). Do **not** copy scripts into `/opt/earthvision` and do **not** modify the live tree.

```bash
# Safety explanation: identity gate runs first; on STOP, no image/compose/env inspection follows.
export APP_DIR=/opt/earthvision
export OUT_DIR="/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ)"
export EXPECTED_HOST=zhzh
export EXPECTED_PROJECT=sateye-fz2ic4
# Do NOT set SKIP_HOST_CHECK

bash /path/to/side-checkout/scripts/e19c_operator_inventory.sh
echo "exit=$?"
# exit 2 => STOP (identity/config failure)
# exit 0 => inventory completed; check share_safe in 00_return_summary.txt / 15_manifest.txt
```

### Command-by-command safety map (what the helper does)

| Step | Evidence file | Safety |
|------|---------------|--------|
| Validate `OUT_DIR` (symlink resolve, ownership, `0700`, outside `APP_DIR`) | (dir only) | Refuses unsafe paths |
| Hostname + `APP_DIR` exist | `01_identity.txt` | STOP on mismatch — **no further inventory** |
| `docker ps` labels → require backend+frontend+proxy **in** `sateye-fz2ic4` | `02_project_services.json`, `STOP.txt` | Other projects ignored; missing service = STOP; **no inspect afterward** |
| Git branch/SHA + baseline ancestor | `04_git.txt` | Read-only; missing → `UNKNOWN` |
| `.env` size/sha256; compose file sha256 | `05_fingerprints.txt` | Never cats `.env` |
| Allowlisted compose **structure** from file | `08_compose_services.txt`, `09_compose_structure.json` | Env **names** + mount destinations only |
| Image Id/digest for **verified** containers only | `06_images.txt` | No host-wide unrelated image dump |
| Mounts for **verified** containers; project-filtered volumes | `10_volumes_mounts.txt` | No data directory reads |
| Health via curl → in-memory parse | `11_health.txt` | **No** `/tmp` health body files |
| Backend env **names** only | `12_env_names.txt` | Values forced `<redacted>` |
| Runner/API allowlisted fields | `13_runner.txt` | No `gh auth status` dump; errors → permission/HTTP codes |
| Secret scan + archive gate | `15_manifest.txt`, optional `STOP_SECRETS.txt` | Archive **only** if `share_safe=yes` |

---

## 5. Manual identity STOP check (if not using helper)

```bash
# Safety: read-only; STOP if any check fails — do not continue manually either.
[[ "$(hostname)" == "zhzh" ]] || { echo STOP_HOST; exit 2; }
[[ -d /opt/earthvision ]] || { echo STOP_APPDIR; exit 2; }
docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}\t{{.Status}}'
# Confirm backend, frontend, and nginx|caddy|traefik|proxy|edge rows with project=sateye-fz2ic4.
# If only sateye-preview (or other) has those services → STOP.
```

---

## 6. Expected output fields

See `00_return_summary.txt` and `E19C_RETURN_TEMPLATE.md`. Every uncertain field must be `UNKNOWN`, `FAIL`, or `STOP` — never implied pass.

Critical fields:

- `identity_result=PASS|STOP`
- `compose_project=sateye-fz2ic4` (only after service-level verification)
- `live_branch`, `live_commit`, `baseline_1e71b7a_ancestor`
- `backend_image_id`, `backend_repo_digest`, `frontend_*`, `proxy_image_id`
- `env_sha256`, `compose_sha256`
- `runner_status`, `actions_runs_api`
- `share_safe=yes|no`, `changes_made=none`

---

## 7. Verification checklist

| # | Check | Result |
|---|-------|--------|
| V1 | Hostname `zhzh` | |
| V2 | `/opt/earthvision` exists | |
| V3 | backend+frontend+proxy containers belong to `sateye-fz2ic4` | |
| V4 | Identity STOP produces no image/env/compose deep inventory | |
| V5 | Live git SHA recorded or `UNKNOWN` | |
| V6 | Image digests for verified services only | |
| V7 | Compose structure allowlisted (no `compose config` dump) | |
| V8 | Volumes/mounts scoped; no data reads | |
| V9 | `.env` fingerprint only | |
| V10 | Baseline ancestor yes/no/object_missing/UNKNOWN | |
| V11 | Health codes + allowlisted fields; no body temp files | |
| V12 | Runner checked without workflow_dispatch | |
| V13 | `share_safe=yes` only if scanner clean | |
| V14 | Archive created **only** when share-safe | |
| V15 | No secrets in bundle | |
| V16 | No production changes | |

---

## 8. Returning sanitized results

1. Open `15_manifest.txt`. If `share_safe=no` or `STOP_SECRETS.txt` exists → **do not share** the bundle; scrub or re-run after fixing.
2. If `share_safe=yes`, send `00_return_summary.txt` plus allowlisted evidence files (or the `.tar.gz` named in the manifest).
3. Fill `E19C_RETURN_TEMPLATE.md`.
4. Do not request Deploy SATEYE / Stage E2 in the same return unless separately authorized.

---

## 9. Blockers this inventory can resolve

| ID | Resolvable? |
|----|-------------|
| B-HOST | Yes (host+dir+**service-scoped** project) |
| B-DIGESTS | Yes (verified services) |
| B-OVERLAY inspect | Partial (structure names/mounts) |
| B-RUNNER | Yes/Partial (allowlisted API/UI) |
| B-CI live token | Partial |
| B-TRUST live | Partial (env **names** only) |
| B-KEYS / Deploy / E2 | No |

---

## 10. GO / NO-GO for operator execution

**NO-GO until the owner explicitly authorizes running this inventory on production.**

E1.9C-R1 corrects helper safety; it does **not** authorize production execution by itself.

After a clean sanitized return: still **NO-GO** for Host Shell deploy until a separate approval.

---

**END OF E1.9C-R1 RUNBOOK**
