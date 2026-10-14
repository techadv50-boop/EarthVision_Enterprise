# Stage P1.1 Security Test Report

**Date:** 2026-10-14  
**Branch:** `cursor/sateye-plugin-manager-p1-5d6d`  
**Reviewed head before hardenings:** `eecf836e2694b645ff967ddd1a3af09e2763f601`  
**Baseline:** `e3012ce0a26e049d0af981d5994d0d829c3b647e`

## Commands

```bash
cd backend
export DATABASE_URL=sqlite+aiosqlite:///./test_p1.db
export SECRET_KEY=ci-test-secret-key-at-least-32-characters
pytest -q \
  app/tests/plugins/test_plugin_manager_p1.py \
  app/tests/tools/test_manifest_integrity.py \
  app/tests/tools/test_true_color_poc.py \
  app/tests/tools/test_ship_detection_canary.py

python scripts/tests/test_core_protection_p11.py
BASE_SHA=e3012ce python scripts/tools/check_core_protection.py
python scripts/tools/check_manifest.py
```

## Results

| Suite | Result |
|-------|--------|
| Plugin manager + P1.1 security (17) | **PASS** |
| Manifest + true_color PoC + ship_detection canary | **PASS** (combined 37 with plugin tests) |
| Core protection adversarial script | **PASS** |
| Core protection vs baseline `e3012ce` | **PASS** (bootstrap; checker not on base yet) |
| Manifest 151/148 | **PASS** |

## Adversarial coverage

| Issue | Test |
|-------|------|
| `CORE_RELEASE=approved` bypass | `test_standalone_core_release_env_rejected` |
| Missing / bad git base | `test_missing_base_fail_closed` |
| Dirty self-protect vs live base | `test_dirty_self_protect_fails_against_live_base` |
| Invalid signatures / slots / host API | plugin tests |
| Zip traversal / entry bomb | `test_zip_traversal_rejected`, `test_zip_entry_limit` |
| Digest-bound install only | `test_digest_mismatch_refuses_install` |
| No `EV_ARTIFACTS_ROOT` mutation | `test_no_env_mutation_during_validate` |
| Concurrent registry + install race | `test_concurrent_validate_and_registry` |
| No in-process plugin import | `test_run_synthetic_does_not_import_plugin_py` |
| Legacy true_color pin | `test_legacy_true_color_pin_untouched` |

## Production

**No production deployment occurred.** No production volumes, containers, or Tool Pack activations were modified.
