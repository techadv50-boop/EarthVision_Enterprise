# Earth Vision Tool Registry (Stage C)

Version-protection layer for the ~148 catalog tools. **Does not enable independent per-tool deployment** — production still ships one full app image via Deploy SATEYE on `cursor/scene-download-eye-5d6d`.

## Files

| File | Purpose |
|------|---------|
| `manifest.json` | Canonical registry: id, version, status, paths, tests, rollback refs |
| `../scripts/tools/check_manifest.py` | Validate manifest ↔ catalog consistency |
| `../scripts/tools/check_approved_guard.py` | Fail if approved-tool paths change without a version bump |
| `../backend/app/tests/tools/` | PoC / canary automated tests |

## Status values

- `development` — not protected yet
- `testing` — under validation (regression canary may use this)
- `approved` — immutable at `approved_version` / `approved_commit` until a new version is validated
- `deprecated` — inactive in UI or retired

## Stage C PoC

- **Primary:** `true_color` (approved `1.0.0` at baseline commit)
- **Canary:** `ship_detection` (unrelated detection family)

Baseline tag: `sateye-baseline-20261012-1e71b7a` (immutable; do not move).

## Deploy honesty

Changing an approved tool still requires a **full-app** rebuild/redeploy. The manifest + CI guard only prevent *silent* regressions and force an explicit version bump + tests before those paths land on the deploy branch.
