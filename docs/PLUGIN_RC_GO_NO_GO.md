# Plugin System RC — Explicit GO / NO-GO Checklist

**Candidate branch:** `cursor/sateye-plugin-rc-5d6d`  
**Production deployment:** **NO-GO** without separate explicit human approval.

## Automated / in-repo (this environment)

| Item | Result |
|------|--------|
| Plugin + security + regression tests (68) | **PASS** |
| Frontend production build | **PASS** |
| Worker process isolation + signatures + active pin | **PASS** |
| Replay-resistant grants | **PASS** |
| Sandboxed FE + CSP middleware | **PASS** |
| demo_hello + demo_gis_analysis lifecycle | **PASS** |
| 148 tools / True Color / Ship Detection preserved | **PASS** |
| Core protection not weakened | **PASS** |
| Default worker auth token removed from compose | **PASS** |
| mTLS tooling present | **PASS** |
| Seccomp allowlist wired (preview) | **PASS** |
| GitHub branch protection confirmed via API | **UNKNOWN** |

## Operator / infrastructure (must clear before production GO)

| Item | Status | Exact action |
|------|--------|--------------|
| Enable GitHub branch protection + required CODEOWNERS reviews on locked baselines | **UNKNOWN** | Repo admin: Settings → Branches → protect `cursor/scene-download-eye-5d6d` (and release targets); require Tool Protection checks + CODEOWNERS; re-run `scripts/tools/check_branch_protection_evidence.py` until overall `PASS` |
| Provision production publisher keys (not preview) | **BLOCKED** | Follow `deployment/production/PROD_SIGNING_KEY_PROVISIONING.md`; never commit private keys |
| Issue production mTLS certificates | **BLOCKED** | Replace preview CA with org PKI; set `EV_PLUGIN_WORKER_TLS=1` + hostname verification |
| Set unique `EV_PLUGIN_WORKER_AUTH_TOKEN` in secret store | **BLOCKED** | Inject via Dokploy/secret manager; ≥32 chars; not in git |
| Apply production Compose/Dokploy worker sidecar | **BLOCKED** | Operator change ticket; **not** this agent; do not touch live `sateye.xdgen.com` until approved |
| Kernel nftables on prod hosts | **BLOCKED** | Adapt `apply_plugin_worker_nftables_preview.sh` under change control |
| Backup/restore drill of `tool_packs` volume | **BLOCKED** | Operator executes and attaches evidence |
| Explicit production deploy approval from product owner | **BLOCKED** | Required written approval |

## Decision

| Scope | Decision |
|-------|----------|
| Merge RC into production branch | **NO-GO** |
| Deploy to `sateye.xdgen.com` | **NO-GO** |
| Continue preview validation / code review of RC PR | **GO** |
| Production deploy | **NO-GO** until all BLOCKED/UNKNOWN rows cleared + separate approval |
