# SAT EYE Offline Mode

SAT EYE is the offline PC edition of the Earth Observation workspace.

## Runtime guarantees

- No outbound calls to Copernicus, Cesium Ion, Stripe, or geocoding APIs
- Imagery enters the system only via **user upload**
- Basemap tiles are generated/cached under `offline_data/basemap`
- Landmarks, coastlines, graticule, and sample DEM/DTM/DSM ship with the install
- Auth wall is disabled when `OFFLINE_MODE=true` (local operator session)

## Multi-date slider

`ImageryStackService` groups uploads by place name / proximity. When a stack has ≥2 images, the UI shows a date slider. A 20-date demo stack (`demo_valley`) is seeded on startup.

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
