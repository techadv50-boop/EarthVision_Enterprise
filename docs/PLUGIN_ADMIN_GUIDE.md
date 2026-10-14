# Plugin Manager — Installation & Administration Guide (RC)

## Audience

SATEYE administrators operating a **preview** or future production deployment.
Does not grant access to Host Shell secrets or Docker sockets.

## Prerequisites

- Admin role in SATEYE  
- Signed plugin zip from a trusted publisher  
- Plugin worker healthy (`Admin → Plugin Manager → Subsystem health`)  
- `EV_PLUGIN_WORKER_AUTH_TOKEN` set (≥32 chars; never commit)  
- Optional: mTLS certs generated via `scripts/tools/generate_plugin_worker_mtls_certs.py`

## Lifecycle

1. **Upload / Validate** — Admin UI → choose zip → Validate. Note `staging_id` + digest.  
2. **Install** — Install validated staging (inactive). Does **not** change Host Shell images.  
3. **Activate** — Select version → Activate. Registry pin (version+digest) becomes active for worker + FE.  
4. **Use** — Sandboxed iframe appears in the declared slot; Host SDK calls are permission-gated.  
5. **Upgrade** — Install newer immutable version → Activate. FE assets swap with pin.  
6. **Rollback** — Rollback to prior version or `inactive`.  
7. **Disable** — Stops FE serving and worker authorization for the plugin.

## Compatibility checks

Before activate, ensure:

- `host_sdk` range includes Host `1.1.0`  
- Slot is one of: `left_toolbar`, `right_analysis_panel`, `map_overlay`, `results_panel`  
- Permissions only from the allowlist  
- Signature verifies under current trust profile  

Health badges show: Host SDK version, signature requirement, trust profile, worker availability, active count.

## Demonstration packs

| Pack | Purpose |
|------|---------|
| `demo_hello` 1.0.0 / 1.1.0 | Install, FE update between versions, rollback |
| `demo_gis_analysis` 1.0.0 | AOI read + analysis result publish via Host SDK |

## Audit

Admin → Plugin Manager → Audit history. Secrets are redacted.
