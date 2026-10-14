# SATEYE Plugin System — Security Verification Report (RC)

**Branch:** `cursor/sateye-plugin-rc-5d6d`  
**Production:** not deployed

## Checklist

| Control | Status | Evidence |
|---------|--------|----------|
| Publisher signature + digest verify (Host + worker) | **PASS** | engine validate/activate; worker `signatures.py`; adversarial invalid signature tests |
| Publisher key trust / rotation tooling | **PASS** (tooling) | `scripts/tools/rotate_publisher_key.py`; `PROD_SIGNING_KEY_PROVISIONING.md` — **prod keys BLOCKED** until operator provisions |
| Default auth secrets removed from compose | **PASS** | `compose.preview.yml` requires `${EV_PLUGIN_WORKER_AUTH_TOKEN:?…}`; bans named preview defaults in production trust profile |
| Host↔worker auth (Bearer + replay-resistant HMAC grant) | **PASS** | `grant_nonce` + single-use MAC; replay test PASS |
| Host↔worker mTLS | **PASS** (preview tooling) | `generate_plugin_worker_mtls_certs.py` + TLS server/client paths; **prod certs BLOCKED** until operator issues |
| Process isolation (subprocess kill/reap) | **PASS** | P2A.1 tests (loop/crash/mem) |
| Seccomp allowlist | **PASS** (preview) | `seccomp.allowlist.json` wired in compose overlay |
| Resource limits | **PASS** | rlimits + mem/cpu/pids in compose |
| Network: Compose internal + no masquerade | **PASS** | `internal: true`, `enable_ip_masquerade=false` |
| Network: kernel nftables helper | **PASS** (script) | `apply_plugin_worker_nftables_preview.sh` — **requires root on preview host**; production **BLOCKED** |
| Child socket deny | **PASS** | `child_runner._deny_network` |
| FE sandbox (srcdoc, no allow-same-origin) | **PASS** | `SandboxedPluginFrame` |
| SPA CSP headers | **PASS** | `SecurityHeadersMiddleware` |
| Permission enforcement (Host SDK) | **PASS** | allowlist + forbidden methods; GIS APIs gated |
| Audit logging without secrets | **PASS** | redaction tests |
| Active-pin authorization on worker + FE assets | **PASS** | stale/disabled/digest mismatch tests |
| GitHub branch protection + CODEOWNERS reviews | **UNKNOWN** | `gh` API HTTP 403 — see manual action |
| Core protection not weakened | **PASS** | `test_core_protection_p11` PASS |

## Verdict summary

- Automated RC security tests: **PASS** where runnable in this environment  
- Operator/infrastructure-gated items: **UNKNOWN** / **BLOCKED** (never reported as PASS)
