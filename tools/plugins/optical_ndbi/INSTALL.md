# NDBI (Optical)

**Plugin id:** `optical_ndbi`  
**Version:** `1.0.0`  
**Host SDK:** `>=1.5.0,<2`  
**Map presentation:** `processed_preview`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when available)  
**Publisher:** `sateye-optical-indices` (Ed25519 `SIGNATURE.json` required in production)

## Install (Admin only)

1. Deploy Host Shell with SDK **1.5+** (includes `host.renderComposite` / `host.renderIndex`).
2. Production trust: merge `tools/publishers/approved_publishers.optical_indices.json`  
   into the live `EV_PACK_PUBLISHERS` file (volume  
   `/data/tool_packs/publishers/approved_publishers.json`).
3. Admin → Plugins → Upload Plugin → choose the **signed** zip  
   `tools/plugins/optical_ndbi/releases/optical_ndbi-1.0.0.zip`
4. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `sha256:e8aca32ea57640b8a7bb5aa50a5444c885f1a7a7df9ba7e477340455d60e4c01`
