# NDWI (Optical)

**Plugin id:** `optical_ndwi`  
**Version:** `1.0.0`  
**Host SDK:** `>=1.5.0,<2`  
**Map presentation:** `processed_preview`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when available)

## Install (Admin only)

1. Deploy Host Shell with SDK **1.5+** (includes `host.renderComposite` / `host.renderIndex`).
2. Admin → Plugins → Upload Plugin → choose  
   `tools/plugins/optical_ndwi/releases/optical_ndwi-1.0.0.zip`
3. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `sha256:9465c7a9857a372111c1c5e209050ec05b9dfe1288db5c2115acad3f8f9f6ebe`
