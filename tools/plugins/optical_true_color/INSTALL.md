# Install True Color (Optical) 1.0.0

## Why upload failed (422) on current Host

Your Admin health showed:

| Badge | Meaning |
|-------|---------|
| **HOST SDK 1.1.0** | This plugin needs **Host SDK ≥ 1.2.0** (scene / true-color / export APIs) |
| **SIGNATURES REQUIRED** + **TRUST PRODUCTION** | Zip must include `SIGNATURE.json` from an allowlisted production publisher |

Unsigned zip + SDK 1.1 Host → validate rejects.

## Steps (in order)

### 1. Deploy Host with SDK 1.2

Merge / deploy PR stack including [#90](https://github.com/techadv50-boop/EarthVision_Enterprise/pull/90) so Admin health shows **HOST SDK 1.2.0**.

Until then, install cannot succeed even with a perfect zip.

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
