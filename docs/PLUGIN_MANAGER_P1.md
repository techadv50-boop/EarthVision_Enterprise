# Stage P1 — Locked Core & Plugin Manager Foundation

**Baseline:** `cursor/scene-download-eye-5d6d` @ `e3012ce`  
**Branch:** `cursor/sateye-plugin-manager-p1-5d6d`  
**Production:** not touched (no deploy, no volume writes, no pack activate on live)

## Objective

Convert Earth Vision into a protected Host Shell that can accept independently managed plugins — without rebuilding the app or modifying the 148 legacy tools.

## Implemented (this stage)

| Task | Status |
|------|--------|
| A Core protection docs + CI gate | Done — `tools/core_protection.json`, `check_core_protection.py`, CI job |
| B Plugin registry | Done — `backend/app/plugins/registry.py` (inactive by default) |
| C Admin Plugin Manager UI | Done — Admin → Plugins tab |
| D Backend plugin engine | Done — validate / install / activate / disable / rollback + audit (reuses Tool Pack integrity & signatures) |
| E Frontend slots | Done — four slots; shell_facade registry mapping (no arbitrary scripts) |
| F Demo plugin `demo_hello` | Done — synthetic data; artifacts `1.0.0` + `1.1.0` |
| G Automated tests | Done — `backend/app/tests/plugins/test_plugin_manager_p1.py` |

## P1.1 hardenings

- Auditable `CORE_RELEASE_APPROVAL` (rejects standalone `CORE_RELEASE=approved`)
- Fail-closed missing git base; self-protected checker/policy/workflow
- Opaque staging IDs; no production `source_path`; zip limits + digest-bound install
- No process-wide env mutation during verify; cross-worker registry lock
- Plugin Python not executed in FastAPI; static `ui/synthetic.json` only
- Permissions documented as declarations, not a sandbox

## Not in P1 / remaining P2 requirements

- Production publisher key provisioning + live `EV_PACK_PUBLISHERS` volume allowlist
- Merging Tool Pack / plugin compose overlay on production
- Reviewed restricted worker/container execution for nontrivial plugin Python
- Independent frontend loading per secure contract (not unrestricted Module Federation)
- Migrating legacy tools (true_color, etc.) into the plugin registry
- Stage E2 production Tool Pack activation
- Left toolbar / map overlay / results panel host components beyond slot plumbing
- Production deploy of Plugin Manager Host Shell image

## Repository & storage layout

```text
tools/
  core_protection.json              # Protected Host Shell modules
  manifest.json                     # Legacy 148-tool catalog (frozen)
  plugins/
    demo_hello/
      src/                          # Build inputs
      artifacts/<version>/          # Immutable signed packs
  plugin_registry.schema.json

backend/app/plugins/                # Registry, engine, slots, permissions
backend/app/routers/admin_plugins.py
backend/app/routers/plugins.py
backend/app/tests/plugins/

frontend/src/plugins/               # Slot host + DemoHelloPanel
frontend/src/components/admin/PluginManagerSection.tsx
frontend/src/services/pluginService.ts

scripts/tools/check_core_protection.py
scripts/tools/build_demo_hello_plugin.py

# Persistent volume (preview/prod) — same tool_packs volume family:
/data/tool_packs/
  plugin_registry.json
  artifacts/<plugin_id>/<version>/
  publishers/approved_publishers.json
  audit/promotions.jsonl
  staging/
  runtime_pins.json                 # Legacy Tool Pack pins (true_color) — untouched by plugins
```

## Install ≠ activate

1. Validate package (signature, host API, slot, permissions, integrity)
2. Install → immutable artifact + registry `installation_status=installed`, `activation_status=inactive`
3. Explicit activate with `confirm=activate`
4. Disable / rollback without touching legacy tools

## Proposed next stage (P2 — production preparation)

1. Provision production Ed25519 publisher; install allowlist on volume  
2. Merge additive compose overlay for plugin/tool_packs env  
3. Preview E2E rehearsal of demo_hello on non-prod  
4. Operator runbook for upload → validate → install → activate  
5. Only then consider production Host Shell image that includes Plugin Manager (still no legacy tool pack activate unless separately approved)

## Safety

- No arbitrary uploaded code execution outside verified `backend/plugin.py` after signature checks  
- Forbidden permissions: filesystem, network, database, shell, subprocess  
- Legacy `true_color` / `ship_detection` cannot be registered as plugins  
- `pack_ops.ALLOWED_TOOLS` unchanged — plugin engine is separate  
