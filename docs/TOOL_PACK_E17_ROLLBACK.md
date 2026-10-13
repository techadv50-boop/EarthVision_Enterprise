# E1.7 Rollback Procedures

## A) Tool Pack activation rollback (no image rebuild)

Prerequisite: Host Shell already deployed; packs installed on the `tool_packs` volume.

```bash
# Preview example (inside backend container or with EV_* pointing at the volume)
python3 scripts/tools/pack_rollback.py --tool true_color --to 1.0.0 \
  --actor "$USER" --confirm rollback

# Or full builtin fallback (always available)
python3 scripts/tools/pack_rollback.py --tool true_color --to builtin \
  --actor "$USER" --confirm rollback
```

Verify:
- `GET /api/v1/tools/runtime` shows intended pin
- `POST /api/v1/analytics/composite` with `preset=true_color` returns coherent overlay
- Host Shell image digests **unchanged**

Failure handling: pin write is atomic; `.bak` recovers corrupt pins; rollback refuses unsigned/missing targets when signatures are required.

## B) Future one-time Host Shell production deploy rollback

If a Host Shell Deploy SATEYE misbehaves (with pin still `builtin`):

1. Do **not** `docker compose down -v`.
2. Redeploy the prior known-good commit on `cursor/scene-download-eye-5d6d` via Deploy SATEYE (ff history / prior SHA).
3. Live overlays (`.env`, server `docker-compose.yml`, `requirements.txt`) are preserved by `deploy_sateye_live.sh`.
4. Confirm `/health`, homepage, login, true_color builtin composite, ship_detection canary.
5. `tool_packs` volume (if already created) is additive — leaving it mounted with `builtin` pin is safe.

**E1.7 does not run production Deploy SATEYE.** Rehearse B only on preview by rebuilding prior images if needed.
