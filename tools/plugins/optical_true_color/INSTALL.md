# Install True Color (Optical) 1.0.0

## Why upload failed (422) on current Host

Your Admin health showed:

| Badge | Meaning |
|-------|---------|
| **HOST SDK &lt; 1.3.0** | Needs **Host SDK ≥ 1.3.0** (map presentation contract + clearMapLayer; 1.2 true-color APIs still work) |
| **SIGNATURES REQUIRED** + **TRUST PRODUCTION** | Zip must include `SIGNATURE.json` from an allowlisted production publisher |

Unsigned zip + old Host → validate rejects.

**Map presentation is Host-owned** (`prefer_scene_tiles`). See `docs/PLUGIN_MAP_PRESENTATION_CONTRACT.md` — do not patch FE/BE per tool for blur/z-order.

## Steps (in order)

### 1. Deploy Host with SDK 1.3

Deploy Host so Admin health shows **HOST SDK 1.3.0** (presentation contract frozen).

Until then, packs requiring `>=1.3.0` cannot install.

### 2. Allowlist the pack publisher (production volume)

Merge publishers from:

`tools/publishers/approved_publishers.optical_true_color.json`

into the live file pointed at by `EV_PACK_PUBLISHERS` (typically  
`/data/tool_packs/publishers/approved_publishers.json`).

Publisher id: `sateye-optical-tc` (public key only — no private key in git).

### 3. Download signed zip

https://github.com/techadv50-boop/EarthVision_Enterprise/raw/cursor/sateye-optical-truecolor-plugin-5d6d/tools/plugins/optical_true_color/artifacts/optical_true_color-1.0.0.zip

### 4. Admin → Plugins → Validate zip → Install → Activate

Place on **right analysis panel**. Restrict satellites to optical families if desired.

## Notes

- Worker badge **NOT CONFIGURED** does not block this pack (`static_synthetic_only`); Host Shell fulfills imagery.
- Legacy builtin `true_color` pack id stays frozen; this plugin id is `optical_true_color`.
