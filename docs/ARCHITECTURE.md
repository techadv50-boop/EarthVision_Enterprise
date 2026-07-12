# EarthVision Enterprise Architecture

## Overview

EarthVision Enterprise is a production-oriented Earth Observation (EO) platform that combines:

- **GIS globe** (CesiumJS frontend)
- **Satellite imagery search & download** (Copernicus Data Space Ecosystem / CDSE)
- **Raster analytics** (spectral indices, COG, XYZ tiles)
- **ML workflows** (land-cover classification, change detection, flood/water/urban helpers)
- **RBAC + API keys + billing** (FastAPI / SQLAlchemy / Stripe)

```
┌─────────────────┐     HTTPS/JSON      ┌──────────────────────────┐
│  React + Cesium │ ◄──────────────────► │  FastAPI (app.main)      │
│  Vite frontend  │                      │  /api/v1/*               │
└─────────────────┘                      └───────────┬──────────────┘
                                                     │
                     ┌───────────────────────────────┼───────────────────────────────┐
                     ▼                               ▼                               ▼
            ┌────────────────┐            ┌──────────────────┐            ┌─────────────────┐
            │ PostgreSQL +   │            │ Scene / Imagery  │            │ CDSE Catalogue  │
            │ PostGIS        │            │ cache (GeoTIFF)  │            │ + Zipper API    │
            └────────────────┘            └──────────────────┘            └─────────────────┘
```

## Backend layers

| Layer | Path | Responsibility |
|-------|------|----------------|
| Routers | `backend/app/routers/` | HTTP contracts, auth dependencies |
| Services | `backend/app/services/` | Business logic (EO, ML, auth) |
| Models | `backend/app/models/` | SQLAlchemy ORM |
| Schemas | `backend/app/schemas/` | Pydantic request/response |
| Core | `backend/app/core/` | Config, security, dependencies |
| Middleware | `backend/app/middleware/` | Request logging (Loguru) |
| Database | `backend/app/database/` | Async engine / session |

## Imagery pipeline

1. **Search** — `CopernicusService.search_scenes` queries CDSE OData (or mock search). Footprints are parsed from `GeoJson` / `Footprint` (WKT or GeoJSON). Optional AOI filtering uses Shapely intersection.
2. **Download** — `SceneService.download_scene` tries `CopernicusService.download_product` (zipper API with Bearer token). On failure/missing credentials it generates a **6-band Sentinel-2-like GeoTIFF** (B2,B3,B4,B8,B11,B12) with coherent water/vegetation/urban patterns.
3. **Cache** — `CachedScene` stores `file_path`, `footprint_geojson`, `preview_path`, acquisition metadata.
4. **Preview** — RGB PNG from bands 3/2/1 via `SceneService.get_preview_path`.

## Raster band layout

Synthetic and normalized scenes use:

| Band | Index | Sensor analogue |
|------|-------|-----------------|
| Blue | 1 | Sentinel-2 B2 |
| Green | 2 | B3 |
| Red | 3 | B4 |
| NIR | 4 | B8 |
| SWIR1 | 5 | B11 |
| SWIR2 | 6 | B12 |

Indices: **NDVI, NDWI, NDBI (SWIR1−NIR), SAVI, BSI, LST** (optical approximation). AOI clipping uses `rasterio.mask`. Tiles via `RasterService.render_tile` (rio-tiler with Pillow fallback).

## Auth model

- JWT Bearer (`get_current_user`)
- `X-API-Key` header (`get_api_key_user`) — SHA-256 hash lookup on `api_keys`
- RBAC via `require_permission(resource, action)` (admin routes require `admin:all`)

## Migrations

- Runtime: `init_db()` → `Base.metadata.create_all` (dev-friendly fallback)
- Production: Alembic (`alembic/`, `alembic.ini`) with `001_initial_schema`

## Frontend

React + Vite + Cesium. Map tools emit GeoJSON; measure calls `POST /api/v1/geo/measure` with a JSON body.
