# SATEYE Tool Plugin Specification (v1)

## Package layout

```
my_tool/
  pack.json
  SHA256SUMS
  SIGNATURE.json          # Ed25519 over digest
  backend/
    plugin.py             # optional worker entry
  ui/
    panel.html
    plugin.js
    tool-meta.json
    synthetic.json        # optional
```

## pack.json (required fields)

| Field | Type | Notes |
|-------|------|-------|
| `plugin_id` / `tool_id` | string | Unique id (snake_case) |
| `name` | string | Default display name |
| `description` | string | |
| `version` | semver | |
| `digest` | `sha256:…` | Of SHA256SUMS |
| `compatible_host_api` | range | e.g. `>=1.3.0,<2` |
| `frontend_slot` | enum | Preferred default slot (admin may override) |
| `permissions` | string[] | Host SDK + slot permissions |
| `ui_strategy` | string | `sandboxed_iframe` |
| `entry.backend` | path | |
| `entry.ui_entry` | path | |

## tool-meta.json (map presentation — required for map tools)

| Field | Type | Notes |
|-------|------|-------|
| `map_presentation` | enum | **Required for any tool that affects the map:** `prefer_scene_tiles` \| `processed_preview` \| `vector_geojson` |

Host Shell owns tiles vs ImageOverlay, z-order, and Swipe. Plugins never call Leaflet.  
See **`docs/PLUGIN_MAP_PRESENTATION_CONTRACT.md`** (Host SDK 1.3 frozen contract).

Optional placement hints (non-binding; admin configures in wizard):

```json
"placement_hints": {
  "category_path": ["Image Processing", "Enhancement"],
  "execution_slot": "right_analysis_panel",
  "icon": "wrench"
}
```

## Lifecycle

1. Develop → 2. Package → 3. Sign → 4. Upload → 5. Validate → 6. Configure category/slot → 7. Install (inactive) → 8. Activate → 9. Use  
**No Host rebuild.**

## Slots

`left_toolbar` | `right_analysis_panel` | `map_overlay` | `results_panel`

## Signing

Use approved publisher Ed25519 key. See `docs/TOOL_PACK_SECURITY.md` and RC Plugin Manager docs.

## Template

`tools/plugin_template/` — generator scaffold for new tools.
