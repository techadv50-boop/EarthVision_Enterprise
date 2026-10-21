# Install True Color (Optical) 1.1.0 — Host SDK 1.1 absorbable

This pack is designed for the **current SAT EYE Host** surface (same absorbable
API as `demo_gis_analysis`), not the newer 1.2 scene/render/export Host APIs.

## What the live Host accepts

| Surface | This pack |
|---------|-----------|
| **HOST SDK 1.1.0** | Requires `>=1.1.0,<2` |
| Permissions | `synthetic_data`, slot, `read_meta`, `read_aoi`, `set/read_analysis_result` |
| Host methods used | `host.getAoiBounds`, `host.getSynthetic`, `host.setAnalysisResult`, `host.resize` |
| Signatures | Zip includes `SIGNATURE.json` from an allowlisted publisher |

Does **not** declare `host.sdk.read_scene` / `render_true_color` / export perms
(those are rejected by the current Host allowlist).

## Steps

### 1. Publisher allowlist (preview)

On the RC preview volume, publisher id **`rc-verify`** must be enabled
(`EV_PACK_PUBLISHERS`). The shipped zip is signed for `rc-verify`.

For production, re-sign with your production publisher and merge that public key
into the production allowlist (never commit private keys).

### 2. Download signed zip

`tools/plugins/optical_true_color/artifacts/optical_true_color-1.1.0.zip`

### 3. Admin → Plugins → Validate zip → Install → Activate

Place on **right analysis panel**.

### 4. Use

1. Draw an AOI (optional but recommended).
2. Open the plugin → **Publish true-color plan**.
3. Band recipes appear in Host analysis results.
4. Map RGB composite remains Host Shell toolbox **true_color** (legacy builtin)
   on an optical scene — this pack does not call map render APIs.

## Notes

- Legacy builtin `true_color` pack id stays frozen; this plugin id is `optical_true_color`.
- Version **1.0.0** (SDK 1.2 scene/export) is superseded for current Host installs by **1.1.0**.
