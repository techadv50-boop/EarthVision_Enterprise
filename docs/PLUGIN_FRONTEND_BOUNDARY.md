# Plugin Frontend Boundary (P1 / P1.1)

## P1 limitation (explicit)

The Host Shell uses **static first-party component mappings** only
(`frontend/src/plugins/slotRegistry.ts`).

| Slot | P1 status |
|------|-----------|
| `left_toolbar` | Declared; no dynamic remote UI |
| `right_analysis_panel` | Host `DemoHelloPanel` only |
| `map_overlay` | Reserved — host factory later |
| `results_panel` | Reserved — host chrome later |

`P1_STATIC_HOST_MAPPINGS_ONLY = true`. This is a deliberate limitation, not a
full plugin UI loader.

## Secure independent frontend plugin loading contract (not enabled)

Independent UI may be enabled only after all of the following are implemented
and reviewed:

1. **Same-origin only** pack UI URLs under the Host Shell origin (no third-party script hosts).
2. **Integrity**: UI assets covered by pack `SHA256SUMS` / digest; pin must match.
3. **Host SDK externals**: React / react-dom / Leaflet provided solely by the shell; packs must not bundle duplicates.
4. **CSP**: `script-src 'self'` (plus explicit same-origin pack path if needed); no `unsafe-eval` for packs.
5. **No unrestricted Module Federation**: shared scopes limited to an allowlisted Host SDK surface; remote entry must be digest-pinned.
6. **Capability gate**: pack may only call documented Host SDK slot/overlay APIs.
7. **Fail closed**: unknown slot or missing host mapping → render nothing (no `eval`, no arbitrary `import(url)`).

## Explicitly forbidden in P1.1

- Arbitrary remote JavaScript URLs
- Unrestricted Module Federation remotes
- Loading unsigned or digest-mismatched UI bundles
- Injecting `<script>` tags from pack metadata

See also `docs/TOOL_PACK_FRONTEND_LOADING.md` (legacy Tool Pack façade notes).
