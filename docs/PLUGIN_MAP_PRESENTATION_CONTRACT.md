# Permanent Host Map Presentation Contract (Host SDK 1.3)

**Status:** frozen for Host Shell presentation  
**Goal:** new tools change **only the plugin pack** — not frontend/backend presentation code.  
**Also see:** `docs/HOST_GEOSPATIAL_INFRASTRUCTURE.md` (Host-shared RS/GIS library profile `sateye-rs-2026.10`).

## Why True Color blur was a Host bug (not a plugin bug)

The True Color plugin correctly called `host.renderTrueColor`. The Host Shell then put a soft **2048px ImageOverlay** on top of sharp Eye-On XYZ tiles (and Swipe near 100% made that worse).

Plugins must **never** touch Leaflet, z-order, swipe, or ImageOverlay vs tiles. Presentation is **Host-owned** and shared by every tool.

Rebuilding frontend/backend for each tool’s look-and-feel will conflict as inventory grows. Do not add per-tool forks in `WorkspacePage`.

## Frozen presentation modes

Declare exactly one in `ui/tool-meta.json` → `map_presentation`:

| Mode | Use when | Host behavior |
|------|----------|---------------|
| `prefer_scene_tiles` | Natural / visual true-color that matches Eye-On TCI | Applied layer draws **sharp XYZ tiles**; soft PNG kept for GeoTIFF export only; duplicate scene hidden; Swipe **off** |
| `processed_preview` | False color, indices, change, classify, stretch | Soft PNG ImageOverlay on top of scene; Swipe **on** for compare |
| `vector_geojson` | Detections / outlines | GeoJSON only; scene tiles stay visible; Swipe **off** |

Implementation (single place): `frontend/src/map/presentMapLayer.ts`  
Map draw rule: `frontend/src/map/LightMap.tsx` — `tileUrl` → TileLayer, else `url` → ImageOverlay.

## Host SDK methods (plugins may call)

| Method | Permission | Role |
|--------|------------|------|
| `host.getSceneContext` | `host.sdk.read_scene` | Read active scene / optical gate / band recipe |
| `host.renderTrueColor` | `host.sdk.render_true_color` | Host computes true color **and** presents via `prefer_scene_tiles` |
| `host.clearMapLayer` | `host.sdk.clear_map_layer` | Hide presented layer(s); restore scenes |
| `host.exportGeotiff` / `host.exportMapJpeg` | export perms | Host owns export chrome |
| `host.setAnalysisResult` | `host.sdk.set_analysis_result` | Results panel text only (**no map pixels**) |

Forbidden forever: `host.leaflet`, `host.map`, sending huge `overlay_base64` through `setAnalysisResult`, iframe Leaflet/React.

## Basic requirements to generate a new plugin (no Host rebuild)

1. **Pack layout** per `docs/PLUGIN_FIRST_TOOL_SPEC.md` (signed zip + `SHA256SUMS` + `SIGNATURE.json`).
2. **`ui/tool-meta.json` must include:**
   - `plugin_id`, `ui_strategy: "sandboxed_iframe"`, `frontend_slot`
   - `permissions` (exact Host SDK tokens you call)
   - `host_sdk.version`: `">=1.3.0,<2"` (or `>=1.2.0,<2` if you only use 1.2 methods)
   - **`map_presentation`**: one of `prefer_scene_tiles` | `processed_preview` | `vector_geojson`
   - `optical_only` / `applicable_satellites` when gated
3. **UI (`plugin.js`)** may only `postMessage` Host SDK methods. No Leaflet, no React, no fetch with tokens.
4. **Map apply:**
   - Prefer a **host compute method** (like `host.renderTrueColor`) so Host presents with your declared mode.
   - Do **not** invent a new Host SDK method per product UI tweak.
   - Do **not** ask for frontend/backend changes to fix blur/z-order/swipe — fix the pack’s `map_presentation` or compute path.
5. **Results chrome:** `host.setAnalysisResult({ title, summary, metrics })` only.
6. **Clear:** `host.clearMapLayer({ layer_id?, label_includes?, restore_scenes? })` on uncheck / reset.
7. **Exports:** call Host export methods; Host keeps soft PNG for GeoTIFF when using `prefer_scene_tiles`.
8. **Install:** Admin → Upload → place in Tool Tree → Activate. **No Host rebuild.**

## What stays frozen in Host (FE/BE)

- Presentation engine: `presentMapLayer` / `clearMapLayer`
- Draw stack: `LightMap` tileUrl vs ImageOverlay + Layers/Swipe
- Host SDK allowlist + permissions
- Composite preview size budget (default 2048) for soft previews / export

## What plugins own

- Band recipes / algorithms / worker compute
- Panel copy, gates, metrics
- Declared `map_presentation` + permissions
- Pack signing / version bumps

If a new tool needs a **fourth** presentation mode, extend `presentMapLayer.ts` once (Host change), document it here, then all future tools reuse it — never special-case one plugin in `WorkspacePage`.
