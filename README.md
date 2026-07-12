# EarthVision Enterprise

Production-grade Earth Observation Platform combining GIS visualization, remote sensing, satellite imagery analytics, and machine learning in a unified commercial platform.

## Features

- **3D Globe Visualization** — CesiumJS-powered interactive globe with terrain, base maps, and Google Earth-style navigation
- **Location Search** — Geocoding, coordinate search, bookmarks, fly-to navigation
- **AOI Drawing** — Polygon, rectangle, circle drawing with GeoJSON import/export
- **Satellite Imagery** — Copernicus Data Space integration for Sentinel-1/2, Landsat, MODIS
- **Remote Sensing Analytics** — NDVI, NDWI, NDBI, SAVI, BSI, LST indices with time series
- **Machine Learning** — Random Forest, SVM, Deep Learning classification and change detection
- **Commercial Features** — JWT auth, RBAC, subscriptions, API keys, admin panel
- **Report Generation** — PDF, Excel, CSV exports

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.x, Pydantic v2, Loguru |
| Frontend | React 19, TypeScript, Vite, CesiumJS, Tailwind CSS, Zustand |
| Database | PostgreSQL + PostGIS (SQLite for local dev) |
| GIS/RS | GDAL, Rasterio, GeoPandas, Shapely, scikit-learn, PyTorch |
| Deployment | Docker, Docker Compose, Nginx, GitHub Actions |

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 22+
- PostgreSQL 16+ with PostGIS (optional — SQLite used by default)

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir .
```

API docs: http://localhost:8000/api/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

### Default Credentials

| User | Password | Role |
|------|----------|------|
| admin | Admin@123456 | Administrator |
| demo | Demo@123456 | Analyst |

### Docker

```bash
docker compose up -d
```

Access via http://localhost:8080

## Project Structure

```
EarthVision_Enterprise/
├── backend/          # FastAPI application
├── frontend/         # React + CesiumJS application
├── database/         # PostgreSQL init scripts
├── docker/           # Dockerfiles and Nginx config
├── deployment/       # Deployment configs
├── docs/             # Documentation
├── scripts/          # Utility scripts
├── tests/            # Integration tests
├── config/           # Shared configuration
├── cache/            # Imagery and scene cache
├── uploads/          # User uploads
└── logs/             # Application logs
```

## API Endpoints

| Module | Prefix | Description |
|--------|--------|-------------|
| Auth | `/api/v1/auth` | Login, register, JWT refresh |
| Geo | `/api/v1/geo` | Search, bookmarks, AOI, measurements |
| Imagery | `/api/v1/imagery` | Scene search, download, Copernicus OAuth |
| Analytics | `/api/v1/analytics` | Indices, ML, change detection, reports |
| Admin | `/api/v1/admin` | Users, roles, projects, API keys |
| Raster | `/api/v1/raster` | Upload, COG conversion, import/export |

## License

Proprietary — EarthVision Enterprise © 2026
