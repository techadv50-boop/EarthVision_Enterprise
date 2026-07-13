# EarthVision Enterprise

Commercial Earth Observation Platform combining interactive 3D globe visualization, satellite catalog search (Copernicus / Sentinel / Landsat / MODIS), spectral analytics, GIS tools, and machine learning — in one integrated product.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, JWT |
| Frontend | React 19, TypeScript, Vite, CesiumJS, Tailwind, Zustand |
| Database | PostgreSQL + PostGIS (SQLite for local dev) |
| Deploy | Docker Compose, Nginx, GitHub Actions |

## Quick Start (local)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # or use the included .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

Default admin: `admin@earthvision.io` / `EarthVision@Admin2024!`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

### Docker Compose

```bash
docker compose up --build
```

## Features

- JWT auth, RBAC, admin panel, subscriptions, API keys
- CesiumJS 3D globe with terrain, basemaps, layer manager
- Location search, fly-to, markers, bookmarks, mouse coordinates, compass
- AOI drawing (polygon / rectangle / circle), GeoJSON & KML import/export
- Copernicus CDSE OAuth2 + Sentinel-1/2, Landsat, MODIS catalog search
- Scene preview, download/cache, footprint overlay
- Raster tile engine (XYZ) with synthetic / GeoTIFF support
- NDVI, NDWI, NDBI, SAVI, BSI, LST + histograms & time series
- Random Forest, SVM, deep learning MLP, change detection
- PDF / Excel / CSV reports

## Copernicus credentials (optional)

Set in `backend/.env`:

```
COPERNICUS_USERNAME=your_cdse_user
COPERNICUS_PASSWORD=your_cdse_password
```

Without credentials the catalog returns realistic demo scenes so the full UI remains usable.

## License

Proprietary — EarthVision Technologies
