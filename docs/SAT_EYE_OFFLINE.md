# SAT EYE Offline Mode

SAT EYE is the offline PC edition of the Earth Observation workspace.

## Runtime guarantees

- No outbound calls to Copernicus, Cesium Ion, Stripe, or geocoding APIs
- Imagery enters the system only via **user upload**
- Basemap tiles are generated/cached under `offline_data/basemap`
- Landmarks, coastlines, graticule, and sample DEM/DTM/DSM ship with the install
- Server listens on `0.0.0.0` so field clients can reach the same data over LAN/VPN
- Login is required when `REQUIRE_LOGIN=true` (default for server/field use)

## Accounts

| User | Password | Notes |
|---|---|---|
| `admin` | `Admin@123456` | Administrator |
| `client` | `Client@123456` | Field client |
| `demo` | `Demo@123456` | Demo analyst |

**Master password-reset code:** `NTZHSS` (`MASTER_RESET_CODE`)

`POST /api/v1/auth/reset-password` with `{ username, master_code, new_password }` resets any client account without being logged in.

## Multi-date slider

`ImageryStackService` groups uploads by place name / proximity. When a stack has ≥2 images, the UI shows a date slider. The slider range is **0 … image_count−1** (maximum = number of available dated images for that place). A 20-date demo stack (`demo_valley`) is seeded on startup.

## Upload metadata

`POST /api/v1/offline/stacks/upload` requires:

| Field | Required | Notes |
|---|---|---|
| `place_name` | yes | Groups images of the same place |
| `acquisition_date` | yes | `YYYY-MM-DD` |
| `acquisition_time` | no | `HH:MM` / `HH:MM:SS` |
| `longitude` / `latitude` / `altitude_m` | no | Location |
| `cloud_cover`, `sensor`, `platform`, `resolution_m`, `notes`, `label` | no | Optional metadata |

## Multi-format ingest

`GET /api/v1/offline/formats` lists accepted extensions (GeoTIFF, JPEG2000, JPG/PNG/WebP, HDF/NetCDF, IMG, ASCII grid, etc.). Uploads are normalized to a **working GeoTIFF** so all 148 GIS tools can run on any accepted format.

## GIS tools

`GET /api/v1/offline/tools` returns all 148 tools. `POST /api/v1/offline/tools/run` executes a tool against local parameters/files.

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/offline/status` | Offline health summary |
| GET | `/api/v1/offline/basemap/{z}/{x}/{y}.png` | Offline basemap tile |
| GET | `/api/v1/offline/layers` | Basemap / DEM / vector catalog |
| GET | `/api/v1/offline/layers/{id}/geojson` | Vector GeoJSON |
| GET | `/api/v1/offline/tools` | List 148 GIS tools |
| POST | `/api/v1/offline/tools/run` | Run a tool |
| GET | `/api/v1/offline/stacks` | Multi-date place stacks |
| POST | `/api/v1/offline/stacks/upload` | Upload image into a place stack |
