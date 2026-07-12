# EarthVision Enterprise Deployment

## Prerequisites

- Python 3.11+ (3.13 supported in Docker image)
- Node.js 20+
- Docker / Docker Compose (recommended for Postgres+PostGIS)
- GDAL system libraries for rasterio (provided in `docker/Dockerfile.backend`)

## Environment

Copy `.env.example` to `.env` and set at minimum:

```env
SECRET_KEY=change-me-to-a-long-random-string-32+
DATABASE_URL=postgresql+asyncpg://earthvision:earthvision@localhost:5432/earthvision
# Optional CDSE
COPERNICUS_CLIENT_ID=
COPERNICUS_CLIENT_SECRET=
# Optional Stripe
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
CESIUM_ION_TOKEN=
```

Local SQLite works out of the box if `DATABASE_URL` is unset (`sqlite+aiosqlite:///.../earthvision.db`).

## Quick start (scripts)

From the repository root on Windows:

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

Seed demo data (admin user is also created on first API boot):

```powershell
python .\scripts\seed.py
```

Default admin: `admin` / `Admin@123456`

## Backend manually

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = (Get-Location).Path
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend manually

```powershell
cd frontend
npm install
npm run dev
```

## Docker Compose

```powershell
docker compose up --build
```

Services:

- **backend** — FastAPI on `:8000` (`docker/Dockerfile.backend` copies `backend/` and `config/`)
- **frontend** — nginx static build
- **db** — PostGIS; initializes via `database/init.sql`

## Database migrations

Dev fallback: on startup FastAPI runs `Base.metadata.create_all`.

Production:

```powershell
# from repo root, with PYTHONPATH=backend
$env:PYTHONPATH = "$PWD\backend"
alembic upgrade head
```

Alembic config: `alembic.ini` + `alembic/env.py` (reads `database_url` from settings).

## Cache directories

Created automatically by settings validators:

- `cache/scenes` — downloaded / synthetic GeoTIFFs
- `cache/imagery` — index & ML outputs
- `uploads` — user uploads/exports
- `logs` — Loguru rotating logs

Admin `/admin/stats` reports real `storage_used_gb` across these dirs.

## CDSE download

When a user has linked Copernicus OAuth (or a valid stored token):

`GET https://zipper.dataspace.copernicus.eu/odata/v1/Products({id})/$value`

Without credentials, search/download fall back to spatially coherent synthetic scenes so analytics still work offline.

## Production checklist

1. Set strong `SECRET_KEY` and disable `DEBUG`
2. Use Postgres+PostGIS, run Alembic migrations
3. Put uvicorn behind nginx / reverse proxy (see `docker/nginx.conf`)
4. Configure CORS origins to the real frontend origin
5. Mount persistent volumes for `cache/` and `uploads/`
6. Configure Stripe price IDs via `STRIPE_PRICE_PRO` / `STRIPE_PRICE_ENTERPRISE` if billing is enabled
7. Restrict file path inputs so tiles/COG only read under cache/upload roots
