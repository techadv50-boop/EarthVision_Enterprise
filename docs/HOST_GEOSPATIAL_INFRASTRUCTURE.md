# Host Geospatial Infrastructure Lock (`sateye-rs-2026.10`)

**Status: FROZEN** — do not reshape FE/BE presentation or the shared RS stack per plugin.  
**Approach: Host-shared professional stack** (not per-plugin libraries).

## Decision

| Option | Choice |
|--------|--------|
| Each plugin ships its own GDAL/numpy/opencv | **Rejected** — conflicts, huge zips, breaks worker isolation |
| Host installs one shared RS/GIS stack; plugins declare capabilities | **Adopted** |

Plugins remain thin (sandboxed UI + optional stdlib/crypto worker). **All raster/vector compute that needs geospatial libraries runs on the Host** (or via Host SDK methods / Host analytics services).

This matches how ENVI / ERDAS Imagine / ArcGIS Pro work: one professional runtime; tools are modules on top.

## Frozen profile

| Field | Value |
|-------|-------|
| `profile_id` | `sateye-rs-2026.10` |
| `profile_version` | `1.0.0` |
| Code | `backend/app/host_capabilities.py` |
| Python deps | `backend/requirements.txt` (geospatial block) |
| Map presentation | `docs/PLUGIN_MAP_PRESENTATION_CONTRACT.md` |
| Host SDK | `≥1.5.0` (`host.getCapabilities`, map clear/present, `renderTrueColor` / `renderComposite` / `renderIndex`, export) |

## What the Host can support (tool families)

Aligned with common ENVI / ERDAS / ArcGIS Pro remote-sensing workflows:

1. **Radiometry / display stretch** — numpy, pillow, rasterio  
2. **Band math & spectral indices** — composites, NDVI/NDWI/NBR/…  
3. **Filtering / morphology** — scipy, scikit-image, OpenCV headless  
4. **Classification** — scikit-learn + classify overlays  
5. **Change detection** — bi-temporal products + xarray cubes  
6. **Object / ship / anomaly detection** — detection services + vector GeoJSON  
7. **Terrain / DEM derivatives** — slope, hillshade, viewshed, …  
8. **Vector GIS** — shapely, pyproj, shapefile, geopandas  
9. **Raster I/O & GeoTIFF export** — rasterio/GDAL, rioxarray  

Map presentation modes (unchanged): `prefer_scene_tiles` | `processed_preview` | `vector_geojson`.

## Libraries locked on Host (do not duplicate in plugins)

`numpy`, `scipy`, `pillow`, `rasterio` (+ system GDAL), `shapely`, `pyproj`, `pyshp`, `geopandas`, `pyogrio`, `scikit-learn`, `scikit-image`, `opencv-python-headless`, `xarray`, `rioxarray`.

**Not** in the frozen profile (optional later, separate approval): `torch` / GPU deep learning.

**Plugin worker image** stays stdlib + cryptography only.

### Adding a library later without rebuilding the image

Use **Admin → Plugins → Host libraries (no rebuild)** to upload a `.whl` into  
`/data/tool_packs/python_extras`. See `docs/HOST_LIBRARY_INSTALL.md`.

That is the supported “Visual Studio / pip” path: persistent Host volume, **no** `docker compose build`.

## Plugin compatibility rules (append-only Host)

1. Declare `map_presentation` in `tool-meta.json`.  
2. Declare `requires_host_capabilities`: list of capability ids from `host.getCapabilities`.  
3. Call Host SDK / Host analytics — never Leaflet, never vendor GDAL/numpy in the zip.  
4. If a capability is missing, **fail install/validate** — do not silently fork Host.  
5. Need a **new** capability family? Extend `host_capabilities.py` + requirements **once**, bump `profile_version`, document here — then all plugins reuse it.

## Discovery

- Host SDK: `host.getCapabilities` (permission `host.sdk.read_capabilities`)  
- Admin / health: includes `geo_profile` from the same document  

## What we will NOT do later

- Rebuild FE/BE presentation for each new optical/SAR/vector plugin  
- Add one-off libraries inside a single plugin pack that other tools cannot share  
- Let plugins draw on Leaflet or bypass `presentMapLayer`
