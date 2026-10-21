# Backend-only Tool Packs vs Future FE Modules (E1.5)

## Is backend-only sufficient for `true_color`?

**Yes.** True Color has no custom React panel beyond the shared Image Processing buttons. The shell already:

1. Dispatches `process/true_color` from the catalog.
2. Calls `POST /api/v1/analytics/composite`.
3. Places the returned PNG on the Leaflet `ImageOverlay`.

The Tool Pack only needs to own **tone-mapping / encode defaults / messaging**. Host owns scene I/O and map chrome.

## Tools that can stay backend-only (pack algorithm + shell façade)

Examples: `true_color`, `false_color`, agriculture/SWIR/urban composites, spectral indices (NDVI…), histogram stretch, many detection tasks that only return GeoJSON/overlays via existing panels.

## Tools that will eventually need independently loaded FE modules

| Need | Examples |
|------|----------|
| Custom interactive panels / wizards | Complex change-report UIs, multi-step maritime dashboards |
| Tool-specific map drawing modes beyond host tools | Specialized AOI editors |
| Bundled third-party viz widgets | Charts not in the shell |
| Offline-capable tool micro-apps | Rare |

Until Module Federation / externals contract is frozen (`TOOL_PACK_FRONTEND_LOADING.md`), those tools should remain shell-integrated or wait for E2+ FE pack support.
