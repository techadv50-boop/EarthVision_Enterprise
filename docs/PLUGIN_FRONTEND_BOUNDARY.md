# Plugin Frontend Boundary (P1 prototype)

## Decision

P1 does **not** load arbitrary frontend scripts or remote React bundles into the Host Shell.

| Slot | Mechanism |
|------|-----------|
| `left_toolbar` | Declared in pack meta; shell may map to a registered host control |
| `right_analysis_panel` | Host component (`DemoHelloPanel`) via `PluginSlotHost` |
| `map_overlay` | Reserved — future host overlay factory only |
| `results_panel` | Reserved — future host results chrome only |

Plugins ship `ui/tool-meta.json` (signed, integrity-covered). The shell reads metadata and renders **first-party** React components from `frontend/src/plugins/slotRegistry.ts`.

## Why not arbitrary scripts

1. React duplication / Module Federation not frozen for this Host Shell  
2. Leaflet must remain single-instance in the shell  
3. CSP: production should keep `script-src 'self'`  
4. Uploaded JS would bypass the permission model

## Future isolation path (not implemented)

Documented prototype only (same direction as `docs/TOOL_PACK_FRONTEND_LOADING.md`):

1. Host exposes stable SDK externals (`window.__EV_HOST_SDK__` / import map)  
2. Plugin UI built as `build.lib` with `react` / `react-dom` external  
3. Same-origin pack URL under `/api/v1/plugins/...`  
4. Contract tests: plugin UI may only call Host SDK overlay/slot APIs  

Until that contract ships, remote bundles remain blocked.
