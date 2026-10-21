# Plugin Frontend Boundary (P2B)

## Loading model

Independent plugin UI is loaded **only** inside a **sandboxed iframe** built from
integrity-covered pack assets (`ui/panel.html`, `ui/plugin.js`, …).

| Property | Enforcement |
|----------|-------------|
| No privileged React execution | Uploaded JS never `import()`’d / `eval`’d in Host Shell |
| Opaque origin | `sandbox="allow-scripts"` **without** `allow-same-origin` + `srcdoc` |
| Digest binding | FE manifest + assets require active registry `version` + `digest` |
| Host SDK | Versioned postMessage protocol `v=1` (`PLUGIN_HOST_SDK_VERSION=1.2.0`) |
| Permissions | Methods gated by pack permission declarations |
| Secrets | Never injected into iframe boot; audit redacts token/secret fields |

## Approved placement slots

| Slot | Host mount |
|------|------------|
| `left_toolbar` | Workspace map chrome (adjacent to MapToolbar; MapToolbar itself unchanged) |
| `right_analysis_panel` | Right toolbox column |
| `map_overlay` | Map stage overlay layer |
| `results_panel` | Below right analysis column |

## iframe origin strategy

1. Host Shell (authenticated) fetches `GET /plugins/{id}/frontend` then UI assets.
2. Host inlines HTML + `plugin.js` into **`srcdoc`** with `window.__EV_PLUGIN_BOOT__`
   containing only `{pluginId, version, digest, slot, name, hostSdkVersion, parentOrigin}`.
3. iframe `sandbox="allow-scripts"` → **opaque origin** (no Host cookies, no DOM access).
4. Plugin talks to Host via `postMessage`; Host accepts only
   `event.source === iframe.contentWindow` and identity matching the active pin.

## CSP

**Inside srcdoc:**

```
default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline';
img-src data:; font-src data:; base-uri 'none'; form-action 'none';
connect-src 'none'; frame-ancestors 'none'
```

**On direct asset responses** (`GET /plugins/{id}/ui/...`): similar CSP +
`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.

`unsafe-inline` is required for srcdoc bootstrapping; there is **no** `unsafe-eval`,
no remote `script-src`, and `connect-src 'none'` blocks plugin network exfil from
the frame. Privileged API calls go through the Host Shell bridge only.

## Host SDK permission enforcement

| Method | Required permission | Notes |
|--------|---------------------|-------|
| `host.meta` | `host.sdk.read_meta` | Returns pin identity — no secrets |
| `host.getSynthetic` | `synthetic_data` | Host calls worker/static synthetic |
| `host.resize` | *(none beyond active plugin)* | Chrome height only |
| `host.getAoiBounds` | `host.sdk.read_aoi` | Host-provided AOI bbox only — no Leaflet |
| `host.setAnalysisResult` | `host.sdk.set_analysis_result` | Typed results for Host results chrome |
| `host.getAnalysisResult` | `host.sdk.read_analysis_result` | Read back published results |
| `host.getSceneContext` | `host.sdk.read_scene` | Active scene + optical gate + OSINT band recipe |
| `host.renderTrueColor` | `host.sdk.render_true_color` | Host runs true-color composite for optical scenes |
| `host.exportGeotiff` | `host.sdk.export_geotiff` | Host downloads GeoTIFF of true-color overlay |
| `host.exportMapJpeg` | `host.sdk.export_map_jpeg` | Host exports map JPEG at 300/600 DPI (N arrow + scale) |

Forbidden methods (`host.getAuthToken`, `host.leaflet`, `host.fetch`, …) are
rejected client-side and server-side.

Backend bridge: `POST /plugins/{id}/host-sdk` re-checks active pin + permissions.

## Explicitly forbidden

- Arbitrary remote JavaScript URLs / Module Federation remotes
- Loading unsigned or digest-mismatched UI bundles
- Injecting `<script src=…>` from unlisted pack metadata into the Host Shell
- Plugin access to auth tokens, unrestricted APIs, or Leaflet objects
- Fallback production credentials in source

## P1 compatibility

`ui_strategy: shell_facade` packs without `panel.html` are rejected when declaring
`sandboxed_iframe`. Static host component maps remain in-tree only as legacy
reference (`DemoHelloPanel`); **P2B slot rendering uses sandboxed iframes**.

## Related

- `docs/PLUGIN_WORKER_P2A.md` — worker isolation (still required for Python exec)
- `docs/PLUGIN_TRUST_BOUNDARY.md`
- `docs/PLUGIN_FRONTEND_P2B.md` — stage summary + production readiness gaps
