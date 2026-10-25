# SATEYE Tool Plugin Template

1. Copy this folder to `tools/plugins/<your_id>/src`
2. Edit `pack.json` + `ui/tool-meta.json` (ids, permissions, **`map_presentation`**)
3. Implement `ui/` and optional `backend/plugin.py` — **no Leaflet / no Host rebuild**
4. Build SHA256SUMS + sign with an approved publisher key
5. Upload via Admin → Tool Tree → Upload Tool Plugin
6. Choose category + execution slot → Install → Activate

**Required reading:** `docs/PLUGIN_MAP_PRESENTATION_CONTRACT.md`  
Also: `docs/PLUGIN_FIRST_TOOL_SPEC.md`.
