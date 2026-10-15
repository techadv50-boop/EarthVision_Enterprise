# Legacy Tool Preservation & Rollback

## What changed (plugin-first branch)

- Workspace **no longer renders** the hardcoded `TOOLBOXES` catalog.
- Analytical tools appear only via **signed plugins** placed in the **admin tool tree**.
- Clean install tool tree is **empty**.

## What was NOT deleted

| Asset | Location | Status |
|-------|----------|--------|
| Frontend toolbox catalog | `frontend/src/toolbox/catalog.ts` | Preserved (LEGACY ARCHIVE header) |
| Legacy ToolboxPanel UI | `frontend/src/components/workflow/ToolboxPanel.tsx` | Preserved (not mounted) |
| Tool handlers in WorkspacePage | `onTool` / analytics / detection paths | Preserved in source |
| Manifest (151 entries) | `tools/manifest.json` | Preserved |
| Backend tool routers | `analytics`, `detection`, `composite`, … | Preserved |
| User data / DB projects / scenes | production & preview DBs | Untouched by this branch |
| Plugin RC (PR #85) | `cursor/sateye-plugin-rc-5d6d` | Not overwritten |

## Inventory snapshot

Generate anytime:

```bash
python3 scripts/tools/export_legacy_tool_inventory.py \
  -o docs/legacy/LEGACY_TOOL_INVENTORY.json
```

## Optional future migration

Convert selected legacy tools **one by one** into signed plugins using `tools/plugin_template/`.  
Do **not** bulk-auto-convert.

## Rollback to legacy UI (development)

1. Revert workspace mount of `PluginFirstToolsPanel` to `ToolboxPanel` (git revert / cherry-pick reverse).  
2. Or check out pre-plugin-first commit / `cursor/sateye-plugin-rc-5d6d`.  
3. Host Platform images and volumes remain; no production data deletion.

## Production

This branch must **not** be merged or deployed without separate explicit authorization.
