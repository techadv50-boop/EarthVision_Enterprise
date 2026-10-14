# Stage P2A.1 Threat Model — Restricted Plugin Worker Security Close-Out

**Branch:** `cursor/sateye-plugin-worker-p2a-5d6d`  
**PR:** #82  
**Foundation:** P2A @ `5273052` / P1.1 @ `e93c100`  
**Production:** development/preview only — no merge, no prod deploy

## Trust boundary (exact)

```text
┌─────────────────────────────────────┐
│ Host Shell (privileged)             │
│  - authN of humans / sessions       │
│  - registry activate/disable        │
│  - mint HMAC grant + Bearer call    │
│  - NEVER import plugin.py           │
└──────────────────┬──────────────────┘
                   │ Bearer + grant_mac/exp (shared secret)
                   │ plugin_id/version/digest are NOT credentials
                   ▼
┌─────────────────────────────────────┐     RO mount
│ plugin_worker (separate process)    │◄── /tool_packs/artifacts
│  1. require Bearer                  │     + publishers + registry
│  2. verify grant MAC/exp            │
│  3. assert_active_pin (registry)    │
│  4. verify digest + Ed25519 sig     │
│  5. spawn child process / request   │
│  6. timeout → killpg + reap         │
└─────────────────────────────────────┘
```

**Cannot bypass by direct worker requests:** any caller without the Host↔worker
shared secret fails at Bearer (401). A caller with the secret but without a
valid grant bound to `(request_id, plugin_id, version, digest, exp)` fails at
grant verify (401). A valid grant for a disabled / rolled-back / non-active pin
fails at registry gate (403). Signature/`EV_PACK_REQUIRE_SIGNATURE=0` bypass is
refused inside the worker.

## Assets

- Host Shell secrets, DB, Docker socket, legacy 148-tool catalog
- Active plugin pin integrity (version + digest)
- Trusted publisher Ed25519 keys / `approved_publishers.json`
- Worker shared auth token (Host↔worker only)

## Adversaries / attacks

| Attack | Expected outcome | Control |
|--------|------------------|---------|
| Infinite loop in `render()` | Parent times out, `killpg(SIGKILL)`, reap; parent survives | `executor.execute` + `start_new_session` |
| `SystemExit` / crash in child | `ExecError`; parent continues | child JSON `{ok:false}` / nonzero rc |
| Memory exhaustion | RLIMIT_AS / container `mem_limit` / timeout → `ExecError` | child rlimits + compose limits |
| Outbound socket from plugin | `OSError: network disabled…` | `child_runner._deny_network` + compose `internal: true` |
| Call worker without Bearer | HTTP 401 | `auth.require_bearer` |
| Forge grant MAC / omit grant | HTTP 401 | `auth.verify_grant` |
| Use plugin id/version/digest as “auth” | Rejected without Bearer+grant | contract + auth |
| Execute stale / rolled-back version | HTTP 403 | `registry_gate.assert_active_pin` |
| Execute disabled plugin | HTTP 403 | activation_status gate |
| `EV_PACK_REQUIRE_SIGNATURE=0` | `SignatureError` fail-closed | `signatures.verify_pack_signature` |
| Wrong digest / unsigned pack | Reject before load | digest re-verify + Ed25519 |
| Leak Host secrets into worker | Start refused | `assert_isolation_or_die` |
| Mount docker.sock into worker | Start refused (compose must not mount) | isolation check |
| Root / writable rootfs / caps | Non-root 65532, `read_only`, `cap_drop: ALL`, seccomp blocklist | Dockerfile + compose + `seccomp.json` |
| Concurrent executes / repeated timeouts | Children isolated; parent remains healthy | ThreadingHTTPServer + per-request Popen |

## Isolation properties (preserved + P2A.1)

| Property | P2A | P2A.1 |
|----------|-----|-------|
| Separate image / no `app.*` | ✓ | ✓ |
| Non-root, RO FS, dropped caps | ✓ | ✓ + explicit `seccomp.json`, `pids_limit` |
| Process boundary | thread timeout (weak) | **subprocess per request + killpg/reap** |
| Host↔worker auth | none | **Bearer + HMAC grant** |
| Active-pin authorization | Host only | **Worker registry gate** |
| Signature on worker | digest only | **Ed25519 + digest; cannot disable** |
| Network | internal compose net | internal + **child socket block** |
| Secrets absent | ✓ | ✓ (stripped from child env) |

## Residual risk / deferred to P2B

See `docs/PLUGIN_WORKER_P2A.md` § Remaining P2B (updated). Notable residuals:

- Worker shared secret is symmetric (mTLS / SPIFFE not yet)
- Seccomp is an explicit **blocklist** (not a minimal allowlist)
- Network deny in-process is Python `socket` monkeypatch (not kernel netns for bare unit tests); Compose uses `internal: true`
- Branch protection API evidence often **UNKNOWN** without admin `gh` token — operators must confirm in GitHub UI
- No production publisher keys / live overlay / Host Shell image cutover

## Non-goals confirmed

- No production merge or deploy
- Preserve 148-tool Host Shell catalog, `true_color` builtin pin, Ship Detection canary behavior
- Frontend independent plugin loading remains P2B
