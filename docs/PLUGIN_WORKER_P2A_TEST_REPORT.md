# Stage P2A Test Report

**Branch:** `cursor/sateye-plugin-worker-p2a-5d6d`  
**Foundation:** `e93c100` (PR #81 P1.1)  
**Date:** 2026-10-14

## Results

| Suite | Result |
|-------|--------|
| Plugin manager + P2A worker/security tests | **22 PASS** (in `test_plugin_manager_p1.py`) |
| Manifest + true_color + ship_detection canary | **PASS** (42 combined) |
| Core protection adversarial + GitHub enforcement | **7 PASS** |
| Core protection vs `e93c100` | **PASS** (no core machinery weakened) |
| Manifest 151/148 | **PASS** |

## P1.1 close-outs covered

- Fail-closed registry flock (`test_registry_flock_fail_closed`)
- Concurrent activate/rollback (`test_concurrent_activate_and_rollback`)
- CODEOWNERS + `check_core_github_enforcement.py` + operator docs
- Core protection not weakened

## Worker coverage

- Isolation refuses `DATABASE_URL` at worker start
- Executor digest mismatch rejected
- demo_hello 1.0.0 → 1.1.0 → rollback → disable lifecycle
- Host Shell fail-closed when `EV_PLUGIN_WORKER_REQUIRED=1` without worker
- No in-process `load_pack_module` for plugin execution path

## Production

**No production deployment occurred.**
