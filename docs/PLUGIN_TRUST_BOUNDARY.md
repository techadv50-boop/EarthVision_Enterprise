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

## Proposed restricted worker / container model (future nontrivial plugins)

1. **Separate worker image** with no DB credentials, no `.env` secrets, no Host Shell private keys.
2. **gRPC / HTTP localhost** contract: Host Shell sends a typed request; worker returns typed JSON.
3. **Read-only pack mount** of the verified artifact digest only.
4. **Network egress deny** by default; allowlist only if a declared permission + review grants it.
5. **seccomp / non-root / read-only rootfs**; no Docker socket.
6. **Resource limits** (CPU, memory, time); kill on timeout.
7. **No shared Python import path** with the API process (prevents accidental `import app.*`).

Until that design is reviewed and implemented, keep `execution_model=static_synthetic_only`.

## Threat notes

- Staging path injection → mitigated by opaque IDs + digest binding
- Zip bombs / traversal → entry count, decompressed size, path/symlink checks
- Registry races across workers → advisory lock + atomic rename RMW
- Env mutation during verify → removed (`verify_pack_at`)
