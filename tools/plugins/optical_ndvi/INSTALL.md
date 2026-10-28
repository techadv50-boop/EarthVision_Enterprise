# NDVI (Optical)

**Plugin id:** `optical_ndvi`  
**Version:** `1.0.0`  
**Host SDK:** `>=1.5.0,<2`  
**Map presentation:** `processed_preview`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when available)

## Install (Admin only)

1. Deploy Host Shell with SDK **1.5+** (includes `host.renderComposite` / `host.renderIndex`).
2. Admin → Plugins → Upload Plugin → choose  
   `tools/plugins/optical_ndvi/releases/optical_ndvi-1.0.0.zip`
3. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `sha256:552fa1a2915314bb03a5f1e884194f054abaed229b5385019a83da1b746ce9cb`
