# EarthVision Enterprise API

Base URL: `/api/v1`  
Interactive docs: `/api/docs`  
OpenAPI: `/api/openapi.json`

Authentication:

- `Authorization: Bearer <access_token>`
- or `X-API-Key: <raw_key>` (hash matched against `api_keys`)

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness |
| GET | `/api/config` | Public config (Cesium token) |

## Auth (`/auth`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create user |
| POST | `/auth/login` | OAuth2 password form → JWT |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me` | Current user profile |

## Geospatial (`/geo`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/geo/search?q=` | Nominatim geocoding |
| GET | `/geo/reverse` | Reverse geocode |
| CRUD | `/geo/bookmarks` | Saved camera locations |
| CRUD | `/geo/aoi` | Areas of interest |
| POST | `/geo/measure` | Body: `{ "geojson": <string\|object> }` — geodesic area/length |

## Imagery (`/imagery`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/imagery/search` | CDSE / mock scene search (`aoi_geojson` optional) |
| POST | `/imagery/download` | Cache scene; accepts `footprint_geojson`, `product_id`, `metadata` |
| GET | `/imagery/cached` | List cached scenes (includes footprints) |
| GET | `/imagery/footprints` | Footprint Feature-like list |
| GET | `/imagery/preview/{scene_id}` | RGB PNG preview |
| GET | `/imagery/copernicus/auth-url` | OAuth authorize URL |
| POST | `/imagery/copernicus/callback` | Exchange code |
| GET | `/imagery/copernicus/status` | Token status |

### Search body

```json
{
  "collection": "SENTINEL-2",
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-06-01T00:00:00Z",
  "cloud_cover_max": 30,
  "aoi_geojson": "{\"type\":\"Polygon\",\"coordinates\":[...]}",
  "limit": 50,
  "offset": 0
}
```

### Download body

```json
{
  "scene_id": "SENTINEL-2_20240101_000",
  "collection": "SENTINEL-2",
  "footprint_geojson": "{...}",
  "product_id": "uuid-from-cdse",
  "metadata": { "id": "uuid-from-cdse" }
}
```

## Analytics (`/analytics`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/analytics/index` | Compute NDVI/NDWI/NDBI/SAVI/BSI/LST |
| POST | `/analytics/time-series` | Multi-scene index means (uses acquisition dates) |
| GET | `/analytics/histogram/{job_id}` | Histogram of result raster |
| POST | `/analytics/classify` | RF / SVM / deep learning land cover |
| POST | `/analytics/change-detection` | NDVI difference + morphology |
| GET | `/analytics/jobs` | List jobs |
| GET | `/analytics/tiles/{job_id}/{z}/{x}/{y}.png` | Result PNG tile |
| POST | `/analytics/report` | PDF / Excel / CSV |

Index request may include `aoi_geojson` for masked statistics.

## Raster (`/raster`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/raster/info/{file_path}` | Raster metadata |
| GET | `/raster/tiles/{z}/{x}/{y}.png?file_path=` | XYZ PNG tile |
| GET | `/raster/tiles/scene/{scene_id}/{z}/{x}/{y}.png` | Tile from cached scene |
| POST | `/raster/upload` | Upload GeoTIFF |
| POST | `/raster/convert-cog` | Full-res COG + overviews |
| POST | `/raster/import/geojson` | Import GeoJSON file |
| POST | `/raster/import/shapefile` | Import zipped shapefile |
| POST | `/raster/export/geojson` | Export GeoJSON file |

## Admin (`/admin`)

Requires `admin:all` (or superuser) for stats/users/roles.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/stats` | Counts + real `storage_used_gb` |
| GET/PATCH | `/admin/users` | User management |
| GET | `/admin/roles` | Roles + permissions |
| CRUD | `/admin/projects` | User projects |
| GET | `/admin/subscription` | Current plan |
| CRUD | `/admin/api-keys` | Create/list/revoke API keys |

## Billing (`/billing`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/billing/plans` | Plan catalog |
| GET | `/billing/status` | Current subscription |
| POST | `/billing/checkout` | Stripe Checkout session if `STRIPE_SECRET_KEY` set; otherwise plan info |

```json
{
  "plan": "pro",
  "success_url": "http://localhost:5173/billing/success",
  "cancel_url": "http://localhost:5173/billing/cancel"
}
```
