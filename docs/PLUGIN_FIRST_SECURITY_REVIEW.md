# Plugin-First Security Review

| Control | Status | Notes |
|---------|--------|-------|
| Signed packages + digest | **PASS** (inherited RC) | Unchanged Plugin Manager validation |
| Admin-only install / tree mutate | **PASS** | `/tools/*` admin mutations require ADMIN role |
| User tree filters inactive | **PASS** | `build_tree(admin=False)` requires active plugin |
| Sandboxed FE / Host SDK permissions | **PASS** (inherited) | No unrestricted React/Leaflet/token access |
| Worker isolation | **PASS** (inherited RC) | Restricted worker unchanged |
| Category delete safety | **PASS** | Blocks non-empty categories; cycle prevention |
| No Host rebuild on install | **PASS** | Volume + DB only |
| Secrets in git | **PASS** | None added |
| Legacy code retained (not deleted) | **PASS** | Archive docs + inventory |
| Production deploy | **NO-GO** | Preview/dev only |

Adversarial: invalid placement slot → rejected by `validate_slot`; circular category move → `ToolTreeError`.
