# Frontend Tool Pack Loading (E0/E1)

## Goal

Load independently versioned tool UI/metadata into the Earth Vision shell **without** rebuilding the Vite SPA for every tool algorithm change.

## E1 decision (validated for this PoC)

For `true_color`, **algorithm independence is backend-first**:

| Layer | E1 approach |
|-------|-------------|
| Algorithm / GIS output | Versioned Python Tool Pack artifact |
| Map UI | Existing shell (`WorkspacePage` → `/analytics/composite`) |
| Pack “UI” | Static `ui/tool-meta.json` served by the API (no React remote) |

### Why not remote React components in E1?

1. **React dependency sharing** — Vite production builds isolate React unless we introduce Module Federation or `window.React` globals. Either option is a larger shell contract change.
2. **Leaflet integration** — overlays are created via Zustand + `LightMap` ImageOverlay in the shell. A remote React child would still need the host overlay API; shipping another Leaflet copy is unsafe.
3. **CSP** — production nginx should allow only same-origin `/tool-packs/*` (or `/api/v1/tools/packs/*`). No arbitrary third-party script URLs.
4. **Vite production** — `import(dynamicURL)` of an opaque remote ESM that also imports `react` will duplicate React or fail resolution unless the pack is built as a **host-external** bundle.

### Compatible future path (E2+)

1. Shell exposes `window.__EV_HOST_SDK__` (or ESM import map) with React, react-dom, and host hooks as **externals**.
2. Pack UI built with Vite `build.lib` + `rollupOptions.external: ['react','react-dom']`.
3. Shell loads: `const mod = await import(/* @vite-ignore */ meta.ui_module_url)`.
4. CSP: `script-src 'self';` plus pack path under same origin.
5. Contract test: pack UI calls only Host SDK overlay APIs (no direct Leaflet).

Until that contract is frozen and tested, E1 keeps React/Leaflet entirely in the shell.

## Host responsibilities (stable)

- Catalog entry `true_color` stays in `catalog.ts`.
- `runComposite('true_color')` keeps calling the composite façade.
- Façade delegates to the **pinned** pack or **builtin** fallback.
- Optional: show pack version badge from `/api/v1/tools/runtime`.

## Integrity

UI meta files live inside the signed pack directory and are covered by `SHA256SUMS` / pack digest. The shell must not load UI from unsigned paths.
