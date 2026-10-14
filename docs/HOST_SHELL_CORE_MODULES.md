# Host Shell Core Modules (Stage P1)

Protected Host Shell modules. Unauthorized edits are rejected by
`scripts/tools/check_core_protection.py` unless `CORE_RELEASE=approved`.

Canonical path list: `tools/core_protection.json`.

## Modules

| ID | Scope |
|----|--------|
| `authentication` | Auth routers, security, role deps, login/register |
| `map_canvas_layers` | Leaflet map, overlays, toolbar, workflow store |
| `shared_backend_services` | Composite / analytics / detection services + routers |
| `database_infrastructure` | DB session, models, alembic |
| `legacy_tool_implementations` | Frozen true_color packs, `pack_ops`, toolbox catalog |
| `existing_tool_catalog` | `tools/manifest.json` (148 unique tools) + guard scripts |

## Rules

1. Plugin Manager and plugin packs live under **plugin-safe** prefixes and do not require a core release.
2. True Color, Ship Detection, and all other legacy tools are **frozen** — treat them as core.
3. Core changes need a separately approved core release (`CORE_RELEASE=approved` in CI).
4. Full-app Deploy SATEYE remains the Host Shell deploy path; plugins install/activate separately.

## Baseline

- Branch: `cursor/scene-download-eye-5d6d`
- Commit: `e3012ce0a26e049d0af981d5994d0d829c3b647e`
