# Host Shell Core Modules (Stage P1.1)

Protected Host Shell modules. Unauthorized edits are rejected by
`scripts/tools/check_core_protection.py`.

## Authorization (auditable)

`CORE_RELEASE=approved` **alone is rejected**.

Core changes require:

1. `CORE_RELEASE_APPROVAL=<id>`
2. File `tools/core_releases/<id>.json` with `base_sha` equal to the CI comparison base
3. `allowed_modules` / `allowed_paths` covering each core path touched

Protection machinery (`tools/core_protection.json`, the checker, Tool Protection
workflow, `tools/core_releases/`) is **self-protected**. Once the checker exists
on the comparison base, modifications require an approval that **already exists
on that base** (cannot introduce the approval in the same PR that weakens
protection).

Missing / unresolvable `BASE_SHA` → **fail closed**.

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
| `core_protection_machinery` | Self-protected checker / policy / workflow / approvals |

## Baseline

- Branch: `cursor/scene-download-eye-5d6d`
- Commit: `e3012ce0a26e049d0af981d5994d0d829c3b647e`
