# SAT EYE

**Offline Earth Observation software for PC installation.**

SAT EYE lets you upload satellite imagery on a local machine, browse multi-date stacks of the same place with a date slider, run **148 GIS tools**, and work with embedded basemaps, landmarks, DEM / DTM / DSM and vector layers — **without an internet connection**.

## Highlights

- **Offline-first** — no Copernicus, Cesium Ion, or cloud feeds at runtime
- **Local image feed** — upload GeoTIFF / COG satellite scenes from disk
- **Multi-date slider** — when a place has multiple dates (e.g. 20), scrub through them on the globe
- **148 GIS tools** — raster, spectral indices, terrain, vector, classification, measurement, conversion, visualization
- **Embedded reference layers** — offline satellite/topo/dark basemaps, world landmarks, coastlines, sample DEM/DTM/DSM
- **Brand UI** — SAT EYE workspace with Cesium globe (ellipsoid + local tiles)

## Quick start (PC)

### Prerequisites (install once, can be offline thereafter)

- Python 3.11+
- Node.js 20+
- (Optional) GDAL system libs for heavy raster workflows

### Install

```bash
# Linux / macOS / WSL
chmod +x scripts/*.sh
./scripts/install_sateye.sh
```

```bat
REM Windows
scripts\install_sateye.bat
```

### Run

```bash
./scripts/start_sateye.sh
```

Open **http://127.0.0.1:5173**

| Manual start | Command |
|---|---|
| Backend | `cd backend && uvicorn app.main:app --reload --app-dir . --host 127.0.0.1 --port 8000` |
| Frontend | `cd frontend && npm run dev -- --host 127.0.0.1` |

API docs (local): http://127.0.0.1:8000/api/docs

## Using SAT EYE offline

1. **Upload** — open Upload Imagery, enter a place name, select a GeoTIFF
2. **Stack dates** — upload more images of the same place (different dates)
3. **Slider** — with 2+ images (demo includes 20), use the bottom date slider
4. **Layers** — toggle landmarks, coastlines, DEM/DTM/DSM; switch offline basemap
5. **Tools** — open GIS Tools (148) and run operations locally

## Architecture

```
SAT EYE (offline PC)
├── frontend/     React + Cesium + Vite  (SAT EYE UI)
├── backend/      FastAPI offline APIs
│   ├── /api/v1/offline/basemap   procedural offline tiles
│   ├── /api/v1/offline/layers    DEM/DTM/DSM + vectors
│   ├── /api/v1/offline/tools     148 GIS tools
│   └── /api/v1/offline/stacks    multi-date place stacks
├── offline_data/ basemap cache, landmarks, elevation samples
├── uploads/      user satellite imagery
└── scripts/      install & start for PC
```

## Configuration

Copy `.env.example` → `.env`. Key flags:

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` | `SAT EYE` | Product name |
| `OFFLINE_MODE` | `true` | Skip login wall; local operator session |
| `OFFLINE_DATA_DIR` | `./offline_data` | Basemap / DEM / vector store |
| `DATABASE_URL` | SQLite `sateye.db` | Local database |

## GIS tool categories (148)

| Category | Count |
|---|---|
| Raster | 30 |
| Spectral Indices | 20 |
| Terrain (DEM/DTM/DSM) | 22 |
| Vector | 24 |
| Classification | 12 |
| Measurement | 12 |
| Conversion | 14 |
| Visualization | 14 |

## License

Proprietary — SAT EYE © 2026
