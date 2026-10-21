# Imagery resolution tags (tools + satellites)

Not every tool applies to every satellite product. SATEYE captures applicability at
**tool upload** and tags **satellites** so admins can segregate providers by resolution.

## Resolution bands

| Key | Label |
|-----|-------|
| `lte_1m` | ≤1m |
| `lte_2m` | ≤2m |
| `lte_3m` | ≤3m |
| `lte_5m` | ≤5m |
| `lte_10m` | ≤10m |
| `lte_15m` | ≤15m |
| `lte_30m` | ≤30m |
| `lt_30m` | &lt;30m |
| `gt_30m` | &gt;30m |

Shared definition: `backend/app/core/imagery_resolution.py` and
`frontend/src/constants/imageryResolution.ts`.

## Tool upload (developer / admin)

In **Admin → Tool Tree → Upload Tool Plugin**, Step 3 requires:

1. **Imagery resolutions this tool works with** (one or more bands)
2. **Applicable satellites** (optional allowlist of provider keys such as `SENTINEL-2`)

Stored on `tool_placements.applicable_resolutions` / `applicable_satellites`.

API: `POST /tools/placements` accepts those arrays. `GET /tools/resolution-bands`
lists options. Tree responses include the fields on each placement.

## Satellite admin

Each satellite has `resolution_category` (one band key). Admin UI:

- Assign the tag when creating/editing a provider
- Filter the satellite list by resolution category

Built-ins are seeded (e.g. Sentinel-2 → `lte_10m`, Landsat → `lte_30m`, MODIS → `gt_30m`).
Categories ≤5m imply `is_high_resolution` for custom (non-builtin) satellites.

## Find scenes (left sidebar)

Enabled satellites are **grouped by resolution category** (≤10m, ≤30m, >30m, …)
instead of a flat grid, so operators can pick imagery by resolution class.
