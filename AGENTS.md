# EarthVision — Agent instructions

## Cursor Cloud (use online at cursor.com/agents)

This repo is set up so you can work **entirely from GitHub + Cursor Cloud Agents** — no local PC folders required.

### Start online
1. Open https://cursor.com/agents
2. Select repo `techadv50-boop/EarthVision_Enterprise`
3. Prefer base branch `cursor/earthvision-enterprise-platform-5d6d` until it is merged to `main`
4. Ask the agent to implement / fix / test; it will push a branch and open a PR

### Environment
- Config: `.cursor/environment.json`
- Install: `bash scripts/cloud-install.sh` (idempotent)
- Auto terminals: **api** (:8000) and **web** (:5173)

### Login
- URL: http://localhost:5173 (inside the agent VM / remote desktop)
- Admin: `admin@earthvision.io` / `EarthVision@Admin2024!`
- API docs: http://localhost:8000/docs

### Smoke checks
```bash
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@earthvision.io","password":"EarthVision@Admin2024!"}'
```

### Secrets (optional — set in Cursor dashboard, not in git)
- `COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD` — live satellite catalog
- `CESIUM_ION_TOKEN` / `VITE_CESIUM_ION_TOKEN` — Cesium ion
- Override `SECRET_KEY` for non-demo use

Without Copernicus credentials the catalog still returns demo scenes so the UI works.

### Git workflow (home + office)
1. All work lives on GitHub (push from agents or desktop)
2. Never rely on uncommitted files on a PC — commit and push before switching machines
3. On either PC (optional): `git pull` the PR branch if you want a local copy
4. Review and merge PRs on GitHub

### Stack notes
- Backend defaults to **SQLite** in cloud (`DATABASE_URL=sqlite+aiosqlite:///./earthvision.db`)
- Frontend proxies `/api` → `:8000` via Vite
- Detection / terrain / composites need an Eye-On optical scene for best results
