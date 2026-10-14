# Plugin Trust Boundary (Stage P1.1)

## Exact trust boundary

| Layer | What is trusted | What is not |
|-------|-----------------|-------------|
| Host Shell (FastAPI / Uvicorn workers) | Registry I/O, signature verify, static `ui/synthetic.json` read after integrity check | Uploaded `backend/plugin.py` **execution** |
| Permissions manifest | Declarative capability tokens checked at validate/install | **Not a sandbox** — does not restrict OS privileges of any process that might later run plugin code |
| Staging uploads | Opaque server `staging_id`, digest-bound install | Client filesystem paths, path traversal, symlinks |
| Frontend | Static Host Shell component map (`slotRegistry.ts`) | Arbitrary remote JS / unrestricted Module Federation |

## Permissions ≠ sandbox

`permissions` in pack meta is an **allowlist declaration**. It does not:

- isolate memory from the API process
- prevent filesystem / network / database access if code were executed in-process
- replace OS containers, seccomp, or capability dropping

## In-process execution policy (P1.1)

Uploaded plugin Python **must not** execute inside the privileged FastAPI process.

P1 demo output is served only from integrity-covered **`ui/synthetic.json`**.
`backend/plugin.py` remains in the pack for future isolated workers but is not
imported by the API.

Enabling any plugin Python execution requires a **separately reviewed isolation
design** (below) before code is merged.

## Restricted worker / container model (P2A / P2A.1 — preview)

Implemented under `tools/plugins/worker/` (see `docs/PLUGIN_WORKER_P2A.md`,
`docs/PLUGIN_WORKER_P2A1_THREAT_MODEL.md`):

1. **Separate worker image** with no DB credentials, no `.env` secrets, no Host Shell private keys.
2. **Authenticated HTTP** contract: Host Shell sends Bearer + HMAC grant + typed JSON; worker returns typed JSON.
3. **Read-only pack mount** of verified artifacts; worker re-checks digest + Ed25519 signature.
4. **Active-pin gate** on the worker — disabled / rolled-back / stale versions rejected.
5. **Network egress deny** by default (Compose `internal` + child socket block).
6. **seccomp / non-root / read-only rootfs / cap_drop ALL**; no Docker socket.
7. **Resource limits** (CPU, memory, pids, time); **per-request subprocess** with killpg/reap on timeout.
8. **No shared Python import path** with the API process (prevents accidental `import app.*`).

Host Shell default for unconfigured worker remains fail-closed when
`EV_PLUGIN_WORKER_REQUIRED=1`. Static `ui/synthetic.json` path remains available
for P1 demos without worker execution.

## Frontend isolation (P2B)

Independent plugin UI loads in a **sandboxed iframe (srcdoc)** with a versioned
postMessage Host SDK. Uploaded JS never runs in the privileged React Host Shell.
See `docs/PLUGIN_FRONTEND_BOUNDARY.md` and `docs/PLUGIN_FRONTEND_P2B.md`.

## Residual (post-P2B)

mTLS, production keys/overlay, seccomp allowlist, kernel egress, SPA-wide CSP,
and operator-confirmed branch protection — see production readiness gaps in
`docs/PLUGIN_FRONTEND_P2B.md`.

## Threat notes

- Staging path injection → mitigated by opaque IDs + digest binding
- Zip bombs / traversal → entry count, decompressed size, path/symlink checks
- Registry races across workers → advisory lock + atomic rename RMW
- Env mutation during verify → removed (`verify_pack_at`)
