# False Color Composites (Optical)

**Plugin id:** `optical_false_color`  
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
   `tools/plugins/optical_false_color/releases/optical_false_color-1.0.0.zip`
4. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `sha256:0f6d2b8ac014b65b6d54d28a99f95c9bded9f0f594d0f91109607a1bf057d593`
