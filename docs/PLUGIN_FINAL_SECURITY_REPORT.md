# PLUGIN FINAL SECURITY REPORT

**RC branch:** `cursor/sateye-plugin-rc-5d6d` (PR #85)  
**Rule:** Configuration-file presence alone is never **PASS**. Runtime or automated enforcement evidence required. Unexecuted checks are **UNKNOWN** / **INCOMPLETE** / **BLOCKED**.

---

| # | Control | Status | Evidence | Method / artifact | Remediation |
|---|---------|--------|----------|-------------------|-------------|
| 1 | Ed25519 signatures + immutable digests | **PASS** | Valid packs accepted; bad sig rejected in preview; unit suite | Preview validate + `demo_hello_bad_sig.zip`; pytest plugins | None |
| 2 | Publisher trust + rotation procedures | **PASS** (tooling) / **BLOCKED** (prod keys) | `rotate_publisher_key.py`; preview publishers JSON mounted; prod template only | `deployment/production/PROD_SIGNING_KEY_PROVISIONING.md` | Operator provisions prod keys out of git |
| 3 | Active plugin version authorization | **PASS** | Disable rejects synthetic; non-installed version rejected | `final_preview_lifecycle_api.json` | None |
| 4 | Replay-resistant HMAC execution grants | **PASS** | Automated grant/replay tests | `final_pytest_tools.txt`; prior `p2a1_adversarial_pytest.txt` | None |
| 5 | mTLS cert validation / unauthorized clients | **INCOMPLETE** (this preview) | Preview ran with `EV_PLUGIN_WORKER_TLS=0`; certs present under `tools/plugins/worker/certs/` | `final_mtls_certs_meta.txt`; compose TLS paths | Operator: enable TLS=1 in preview/prod and retest unauthorized client |
| 6 | Process isolation, timeouts, child cleanup | **PASS** | Subprocess-per-request; crash/loop/mem unit tests | Plugin pytest + worker health `process_isolation` | None |
| 7 | Kernel network isolation + egress denial | **PASS** (compose runtime) / **UNKNOWN** (host nftables) | Worker `EGRESS_DENIED Network is unreachable`; compose `internal: true`, no masquerade | `final_security_egress.txt` | Optional: run nftables helper as root on host |
| 8 | Seccomp allowlist, rlimits, non-root | **PASS** | Worker uid 65532; seccomp allowlist loaded; healthy after fork/vfork fix; mem/cpu/pids limits | `seccomp.allowlist.json`; worker health JSON | None |
| 9 | FE sandbox, CSP, message origin/source | **PASS** | Sandboxed iframe srcdoc; CSP middleware; message validation unit tests | FE + plugin pytest | None |
| 10 | Host SDK permission enforcement | **PASS** | Permission allowlist; GIS methods gated | `host_sdk_contract.py` + tests | None |
| 11 | Audit logs + secret redaction | **PASS** | 14 audit events; redaction unit tests | lifecycle audit sample | None |
| 12 | Worker unavailable failure behavior | **PASS** (unit) | Fail-closed when worker required/unreachable | pytest PackOpsError path | None |
| 13 | Protection against direct worker access | **PASS** | Host cannot reach `:8091`; worker only on internal net | `final_security_direct_worker.txt` | None |
| 14 | No hardcoded prod secrets / unsafe fallbacks | **PASS** | Compose requires `EV_PLUGIN_WORKER_AUTH_TOKEN:?…`; no default token | `compose.preview.yml` | Keep secrets in secret store only |
| — | Unauthorized worker call (no auth) | **PASS** | Execute path without bearer fails | `final_security_worker_no_auth.txt` | None |
| — | GitHub branch protection / required reviews | **UNKNOWN** | HTTP 403 from GitHub API | `final_branch_protection.json`, `final_gh_protection_rc.txt` | Repo admin enables rules (see OPERATOR_ACTIONS) |

---

## Adversarial / runtime outputs preserved

| Artifact | Content |
|----------|---------|
| `/opt/cursor/artifacts/final_security_egress.txt` | Egress deny from worker |
| `/opt/cursor/artifacts/final_security_direct_worker.txt` | Direct host→8091 refused |
| `/opt/cursor/artifacts/final_security_worker_from_backend.txt` | Backend→worker health OK |
| `/opt/cursor/artifacts/final_security_worker_no_auth.txt` | Unauthenticated execute rejected |
| `/opt/cursor/artifacts/final_preview_lifecycle_api.json` | Bad signature / disable / digest / version rejects |
| `/opt/cursor/artifacts/p2a1_adversarial_pytest.txt` | Prior adversarial suite |
| `/opt/cursor/artifacts/p2b_adversarial_pytest.txt` | Prior P2B adversarial suite |

## Security verdict

- **Development / preview enforceable controls:** largely **PASS**  
- **mTLS runtime unauthorized-client in this preview:** **INCOMPLETE** (TLS disabled for bring-up)  
- **Production key/cert/nftables/GitHub governance:** **BLOCKED** or **UNKNOWN**  
- **Do not treat as production-cleared.**
