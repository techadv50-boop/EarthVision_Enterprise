# Stage P2A — Secure Plugin Execution Worker (Development Only)

**Foundation:** PR #81 @ `e93c100`  
**Branch:** `cursor/sateye-plugin-worker-p2a-5d6d`  
**Production:** no deploy, no production Compose changes, no merge to approved production branch, no activation on `sateye.xdgen.com`

## Architecture

```text
┌──────────────────────────┐         typed JSON /v1/execute        ┌────────────────────────────┐
│ Host Shell (FastAPI)     │ ───────────────────────────────────► │ plugin_worker (separate   │
│ - registry / activate    │ ◄─────────────────────────────────── │  image & Python env)      │
│ - signature verify       │         result | error               │ - non-root, read-only FS  │
│ - NEVER import plugin.py │                                      │ - no DB/secrets/docker    │
└──────────────────────────┘                                      │ - digest re-verify        │
                                                                  │ - timeout + resource caps │
                                                                  └────────────────────────────┘
                                                                            │
                                                                            ▼ RO
                                                                  /tool_packs/artifacts/<id>/<ver>
```

### Isolation properties

| Property | Enforcement |
|----------|-------------|
| Separate from FastAPI | Own image `tools/plugins/worker/Dockerfile`; no `app.*` imports |
| No DB / secrets | Worker refuses start if `DATABASE_URL` / `SECRET_KEY` / … set; compose clears them |
| No Docker socket | Start fails if `/var/run/docker.sock` present |
| Non-root | UID 65532; start fails if root (unless explicit override for broken sandboxes) |
| Read-only rootfs | Compose `read_only: true` + tmpfs `/tmp` |
| Restricted network | Preview overlay: internal compose network only; no published ports |
| Resource / time limits | `mem_limit` / `cpus`; worker execution timeout |
| Signed artifacts only | Host verifies pack; worker re-verifies digest before load |
| Fail closed | `EV_PLUGIN_WORKER_REQUIRED=1` → Host Shell refuses execution without healthy isolated worker |

### Typed contract

See `tools/plugins/worker/contract.py`. Operations: `render`, `ping`.

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

Auditable core changes still need `CORE_RELEASE_APPROVAL` bound to `base_sha` (repository JSON alone is not enough without the GitHub checks/reviews above).

`scripts/tools/check_core_github_enforcement.py` verifies CODEOWNERS + workflow wiring + this doc exist (fail closed in CI).

## Local preview (not production)

```bash
docker compose -p sateye-preview \
  -f docker-compose.preview.yml \
  -f tools/plugins/worker/compose.preview.yml \
  --env-file .env.preview up -d --build
```

## Lifecycle demo (backend)

Install → (inactive) → activate `demo_hello@1.0.0` → execute via worker → install `1.1.0` → activate `1.1.0` → rollback `1.0.0` → disable. Legacy `true_color` pin stays `builtin`.

## Remaining P2B

- Production publisher keys + live overlay (still separate approval)  
- Secure independent frontend loading per contract (no unrestricted JS)  
- Hardened network policies (egress deny beyond compose DNS) / seccomp profile file  
- Worker mTLS between Host Shell and worker  
- Production Host Shell image cutover including worker (not this stage)  
- Branch protection enablement confirmation in GitHub UI (operator action)

## Confirmation

**No production deployment occurred in P2A.**
