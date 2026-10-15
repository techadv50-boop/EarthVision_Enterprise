# Plugin-First Automated Test Report

**Branch:** `cursor/sateye-plugin-first-tree-5d6d`  
**Base RC:** `cursor/sateye-plugin-rc-5d6d` @ `50031d6`

| Suite | Result | Artifact |
|-------|--------|----------|
| `app/tests/test_tool_tree.py` + plugins | **46 passed** | `/opt/cursor/artifacts/plugin_first_pytest.txt` |
| Full `app/tests/` | **133 passed** | `/opt/cursor/artifacts/plugin_first_pytest_full.txt` |
| Frontend `npm run build` | **PASS** | `/opt/cursor/artifacts/plugin_first_frontend_build.txt` |
| Legacy inventory export | **PASS** | `docs/legacy/LEGACY_TOOL_INVENTORY.json` (10 boxes / 151 tools; manifest 151) |

## Coverage highlights

- Empty tree message
- Nested categories + placement + activate visibility
- Disable removes from active tree
- Non-empty category delete blocked
- Circular category move blocked
- Category reorder
- Existing plugin security suite retained
