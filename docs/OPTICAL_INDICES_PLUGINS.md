# Optical Composite & Spectral Index Plugins

**Host SDK:** `≥1.5.0`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when catalogued)  
**Presentation:** `processed_preview` (soft PNG + swipe; Host-owned)  
**Publisher:** `sateye-optical-indices` (production Ed25519)

These packs extend the Host without per-tool frontend forks. Band recipes match `backend/app/services/satellite_bands.py`.

| Plugin id | Method | Products |
|-----------|--------|----------|
| `optical_true_color` | `host.renderTrueColor` | Natural color (`prefer_scene_tiles`) |
| `optical_false_color` | `host.renderComposite` | FCC IR, agriculture, urban, SWIR |
| `optical_ndvi` | `host.renderIndex` | NDVI |
| `optical_ndwi` | `host.renderIndex` | NDWI (McFeeters) |
| `optical_ndbi` | `host.renderIndex` | NDBI |
| `optical_spectral_indices` | `host.renderIndex` | SAVI, EVI, NDMI, NBR, BSI |

## Build

```bash
python3 scripts/tools/build_optical_indices_plugins.py
```

Unsigned artifact trees land under `tools/plugins/<id>/artifacts/`. Production zips must include `SIGNATURE.json` (publisher `sateye-optical-indices`).

## Production trust (required before Validate)

Admin health shows **SIGNATURES REQUIRED** + **TRUST PRODUCTION**. The image-default publishers file is empty; install an allowlist:

1. Copy `tools/publishers/approved_publishers.optical_indices.json` to the live volume:

   `/data/tool_packs/publishers/approved_publishers.json`

2. Set backend env:

   - `EV_PACK_PUBLISHERS=/data/tool_packs/publishers/approved_publishers.json`
   - `EV_PACK_TRUST_PROFILE=production`

3. Recreate backend only (no image rebuild required for the allowlist file).

Publisher ids in that file: `sateye-optical-tc` (true color) and `sateye-optical-indices` (FCC / NDVI / NDWI / NDBI / spectral). Public keys only.

## Install (Admin)

1. Confirm Host health shows Host SDK **1.5.0+** and trust is ready (no red production-trust banner).
2. Upload each **signed** zip from `tools/plugins/<id>/releases/<id>-1.0.0.zip`.
3. Arrange in Tool Tree → Activate.
4. Users only see tools after Admin activation / account tool grants.

## Landsat / Sentinel band notes (examples)

| Product | Sentinel-2 | Landsat-8/9 | Landsat-7 |
|---------|------------|-------------|-----------|
| FCC IR | B08-B04-B03 | B5-B4-B3 | B4-B3-B2 |
| NDVI | B08+B04 | B5+B4 | B4+B3 |
| NDWI | B03+B08 | B3+B5 | B2+B4 |
| NDBI | B11+B08 | B6+B5 | B5+B4 |

Do **not** rebuild Host for new index products that fit `host.renderIndex` / `host.renderComposite` — ship a new pack only.
