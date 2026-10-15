# Plugin-First Preview Demonstration Evidence

**Preview project:** `sateye-preview-pf` (127.0.0.1:8200–8202)  
**Artifacts:** `/opt/cursor/artifacts/plugin_first_demo/`

| Step | Result | Evidence |
|------|--------|----------|
| A Empty tool interface | **PASS** | `demo_lifecycle.json` → `A_empty_tree` message exact |
| B Create Image Processing | **PASS** | category create |
| C Create Enhancement | **PASS** | subcategory under Image Processing |
| D Upload + activate demo | **PASS** | validate/install/activate demo_hello |
| E Place under Enhancement | **PASS** | placement display_name Contrast Enhancement |
| F Open in right analysis panel | **PASS** | `/tools/slots/right_analysis_panel/active` lists tool |
| G Create Airfield | **PASS** | root category |
| H Second tool under Airfield | **PASS** | demo_gis_analysis placed + activated |
| I Reorder categories | **PASS** | Airfield sort_order 0, Image Processing 1 |
| J Disable → disappears | **PASS** | gis hidden; hello remains |
| K Upgrade + rollback | **PASS** | 1.0.0→1.1.0→rollback 1.0.0 |
| L Host containers unchanged | **PASS** | `host_compare.json` `host_unchanged: true` |

Demonstration executed against the **live preview API + running Host Shell containers**. Admin Tool Tree Manager and Install Wizard are mounted in the SPA (`AdminPanel` → Tool Tree / Upload). Browser pixel screenshots were not captured in this run; API + container identity evidence is authoritative for install-without-rebuild.

**Production:** read-only health only (`prod_untouched.txt`).
