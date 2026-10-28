# NDBI (Optical)

**Plugin id:** `optical_ndbi`  
**Version:** `1.0.0`  
**Host SDK:** `>=1.5.0,<2`  
**Map presentation:** `processed_preview`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when available)

## Install (Admin only)

1. Deploy Host Shell with SDK **1.5+** (includes `host.renderComposite` / `host.renderIndex`).
2. Admin → Plugins → Upload Plugin → choose  
   `tools/plugins/optical_ndbi/releases/optical_ndbi-1.0.0.zip`
3. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `sha256:e8aca32ea57640b8a7bb5aa50a5444c885f1a7a7df9ba7e477340455d60e4c01`
