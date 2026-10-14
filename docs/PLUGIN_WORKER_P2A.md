# Stage P2A / P2A.1 — Secure Plugin Execution Worker (Development Only)

**Foundation:** PR #81 @ `e93c100`  
**Branch:** `cursor/sateye-plugin-worker-p2a-5d6d`  
**PR:** #82  
**Production:** no deploy, no production Compose changes, no merge to approved production branch, no activation on `sateye.xdgen.com`

## Architecture

```text
┌──────────────────────────┐   Bearer + HMAC grant + /v1/execute   ┌────────────────────────────┐
│ Host Shell (FastAPI)     │ ───────────────────────────────────► │ plugin_worker (separate   │
│ - registry / activate    │ ◄─────────────────────────────────── │  image & Python env)      │
│ - mint execution grant   │         result | error               │ - Bearer + grant verify   │
│ - NEVER import plugin.py │                                      │ - active-pin registry gate│
└──────────────────────────┘                                      │ - Ed25519 + digest verify │
                                                                  │ - subprocess per request  │
                                                                  │ - killpg/reap on timeout  │
                                                                  │ - non-root, RO, seccomp   │
                                                                  └────────────────────────────┘
                                                                            │
                                                                            ▼ RO
                                                                  /tool_packs/artifacts/<id>/<ver>
```

### Isolation properties (P2A.1)

| Property | Enforcement |
|----------|-------------|
| Separate from FastAPI | Own image `tools/plugins/worker/Dockerfile`; no `app.*` imports |
| Authenticated Host→worker | `EV_PLUGIN_WORKER_AUTH_TOKEN` Bearer + HMAC grant; plugin id/version/digest are **not** auth |
| Active-pin authorization | Worker reads `plugin_registry.json`; rejects disabled / stale / rolled-back |
| Process boundary | Per-request `subprocess.Popen` + `start_new_session`; timeout → `killpg(SIGKILL)` + reap |
| Signature + digest | Worker re-verifies SHA256SUMS digest and Ed25519 `SIGNATURE.json`; refuses `EV_PACK_REQUIRE_SIGNATURE=0` |
| No DB / secrets | Worker refuses start if `DATABASE_URL` / `SECRET_KEY` / … set; compose clears them; child env stripped |
| No Docker socket | Start fails if `/var/run/docker.sock` present (compose must not mount) |
| Non-root | UID 65532; start fails if root (unless explicit override for broken sandboxes) |
| Read-only rootfs | Compose `read_only: true` + tmpfs `/tmp` |
| Restricted network | Preview overlay: `internal: true` network; child blocks `socket.*` |
| Resource / time limits | `mem_limit` / `cpus` / `pids_limit`; child RLIMIT_AS/CPU/NPROC/NOFILE; worker timeout |
| Seccomp | Explicit blocklist `tools/plugins/worker/seccomp.json` + `cap_drop: ALL` + `no-new-privileges` |
| Fail closed | `EV_PLUGIN_WORKER_REQUIRED=1` → Host Shell refuses execution without healthy isolated worker |

Threat model detail: `docs/PLUGIN_WORKER_P2A1_THREAT_MODEL.md`.

### Typed contract

See `tools/plugins/worker/contract.py`. Operations: `render`, `ping`.
Grant fields: `grant_exp`, `grant_mac` (required on `/v1/execute`).

## P1.1 close-outs in this stage

1. Registry **fail closed** if `fcntl`/`flock` unavailable  
2. Concurrent activate/rollback tests  
3. Core approval via **CODEOWNERS** + Tool Protection required checks (documented); JSON approval alone is not enough  
4. Core protection policy **not weakened**

### Required GitHub branch protection (operators)

On the locked baseline / PR target branches, **branch protection** must enable:

1. **required status checks** including Tool Protection / `Guard Host Shell core modules (P1.1)`  
2. **required status checks** that run `scripts/tests/test_core_protection_p11.py` (includes GitHub enforcement script)  
3. Required review from **CODEOWNERS** for paths listed in `.github/CODEOWNERS`  
4. Dismiss stale reviews; no admin bypass for core paths  

Auditable core changes still need `CORE_RELEASE_APPROVAL` bound to `base_sha`
(repository JSON alone is not enough without the GitHub checks/reviews above).

Evidence script: `scripts/tools/check_branch_protection_evidence.py`  
(prints `PASS` only with authorized API confirmation; otherwise **`UNKNOWN`** — never false PASS).

`scripts/tools/check_core_github_enforcement.py` verifies CODEOWNERS + workflow wiring + this doc exist (fail closed in CI).

## Local preview (not production)

```bash
# Set a ≥32-char shared token in .env.preview:
# EV_PLUGIN_WORKER_AUTH_TOKEN=...

docker compose -p sateye-preview \
  -f docker-compose.preview.yml \
  -f tools/plugins/worker/compose.preview.yml \
  --env-file .env.preview up -d --build
```

## Lifecycle demo (backend)

Install → (inactive) → activate `demo_hello@1.0.0` → execute via worker → install `1.1.0` → activate `1.1.0` → rollback `1.0.0` → disable. Legacy `true_color` pin stays `builtin`.

## Remaining P2B work (precise)

1. **Secure independent frontend loading** — Host Shell slot contract only; no unrestricted remote JS / Module Federation; pin UI assets to the same digest as the active backend pack.
2. **Production publisher keys + live overlay** — separate operator approval; no preview keys in prod trust profile.
3. **Worker mTLS / SPIFFE** — replace or augment shared Bearer secret with mutual TLS between Host Shell and worker.
4. **Kernel/netns egress deny** beyond Compose `internal` + Python socket monkeypatch (e.g. network namespace / nftables allowlist per declared permission).
5. **Seccomp allowlist** — move from explicit blocklist to minimal syscall allowlist tuned for CPython worker.
6. **Host Shell production image cutover** including worker sidecar (not this stage; no Dokploy/prod Compose edits here).
7. **Operator confirmation of GitHub branch protection** — enable required checks + CODEOWNERS reviews; re-run `check_branch_protection_evidence.py` until overall `PASS`.
8. **Admin UX for Plugin Manager** — activate/rollback/disable surfaces bound to worker health + isolation report.
9. **Observability** — structured worker audit logs (request_id, pin, grant exp, kill/reap events) without packing secrets.
10. **Non-synthetic nontrivial plugins** — only after P2B FE + mTLS + prod keys; keep `execution_model` gated.

## Confirmation

**No production deployment occurred in P2A / P2A.1.**  
**148 tools / `true_color` builtin pin / Ship Detection canary / Host Shell behavior preserved.**
