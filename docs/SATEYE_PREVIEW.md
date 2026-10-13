# SATEYE Temporary Preview (pre-production)

**Status:** Preview config is prepared in-repo. This does **not** deploy to production.  
**Production (do not modify):** https://sateye.xdgen.com · Dokploy project `sateye-fz2ic4` on host `zhzh`  
**Approved production branch:** `cursor/scene-download-eye-5d6d`  
**Preferred preview URL:** https://sateye-preview.xdgen.com

---

## 1) Branch investigation — most complete version

| Branch | Tip | Relation to production tip | Verdict |
|--------|-----|----------------------------|---------|
| **`cursor/scene-download-eye-5d6d`** | `ac9861c` | **Production tip** | **Most complete — use for preview** |
| `cursor/sateye-pro-tools-5d6d` | `192b743` | Ancestor (PR #27 merged) | Already inside prod; 30 commits behind |
| `cursor/sateye-ship-code-replace-5d6d` | `6e1db78` | Ancestor (PR #44) | Already inside prod |
| `cursor/sateye-nir-optimized-gee-5d6d` | `ee5b2fa` | Ancestor | Already inside prod |
| `cursor/sateye-water-anomaly-detect-5d6d` | `3b05fd9` | Ancestor | Already inside prod |
| `cursor/earthvision-enterprise-platform-5d6d` | `81346ab` | Ancestor | Platform base; 108 commits behind tip |
| `cursor/authentic-ai-detectors-5d6d` | `c0f00a2` | **Diverged** | 7 unique commits, **108 behind**; missing ship module |
| `dokploy-sateye-migration` | `6155991` | Diverged | Ports/secrets isolation only; not more features |

**Recommendation:** Preview **`cursor/scene-download-eye-5d6d` @ `ac9861c`**.  
Do **not** switch production to another branch without explicit approval.  
Newest commit date alone is misleading — `pro-tools` looks “big” but is an older ancestor.

---

## 2) Toolbox audit (code reality, not marketing)

Source of truth: `frontend/src/toolbox/catalog.ts` on production tip.

| Metric | Value |
|--------|------:|
| Catalog entries (“148 tools” claim) | **148** |
| Unique tool IDs | **145** (duplicate ids: `grid`, `clip`, `wind`) |
| Marked `inactive: true` (AI) | **21** |
| Approx. FULL (UI + real backend logic) | **~50** |
| Approx. PARTIAL (thin / synthetic / seeded) | **~70** |
| Approx. PLACEHOLDER (inactive / message-only) | **~28** |

### Category notes

- **Satellite search / eye / download:** Outside the 148 catalog; workflow is largely **FULL** (`/catalog/*`).
- **Composites + spectral indices:** **FULL** via `/analytics/*`.
- **Optical ship detection:** **FULL** (`optical_ship_detection.py`, water AOI + Landsat/S2 eye).
- **Other AI / maritime / aviation detectors:** Mostly **PARTIAL** (seeded/synthetic) or **PLACEHOLDER** (`inactive` on prod tip).
- **Terrain / DEM:** Implemented paths but **synthetic DEM** → PARTIAL.
- **GIS:** Many real Shapely ops via `/gis/*` → mostly FULL/PARTIAL.
- **Admin permissions:** FULL at **10 toolbox categories**, not per-tool ACLs.
- **`pro-tools` branch:** Same 148 count; inflated **apparent** completeness by leaving AI tools active without stronger backends.

**Do not treat a tool as working just because it appears in the UI.**

---

## 3) Isolated preview stack (prepared in repo)

| Item | Production | Preview |
|------|------------|---------|
| Compose file | Dokploy / `docker-compose.yml` | **`docker-compose.preview.yml`** |
| Project name | `sateye-fz2ic4` | **`sateye-preview`** |
| Host ports | typically `8100–8102` | **`127.0.0.1:8200–8202`** |
| DB / volumes | production pgdata | **`sateye_preview_*` named volumes only** |
| Admin login | production admin | **`preview-admin@xdgen.com` / `PreviewOnly123`** (change in `.env.preview`) |
| Domain | `sateye.xdgen.com` | **`sateye-preview.xdgen.com`** (DNS required) |

Files added:
- `docker-compose.preview.yml`
- `deployment/nginx.preview.conf`
- `.env.preview.example`
- `scripts/start_sateye_preview.sh`

### Start on server `zhzh` (manual, outside prod Dokploy project)

```bash
cd /path/to/EarthVision_Enterprise   # checkout cursor/scene-download-eye-5d6d
cp .env.preview.example .env.preview
# edit .env.preview secrets
chmod +x scripts/start_sateye_preview.sh
./scripts/start_sateye_preview.sh
```

Local smoke (on the host):
- http://127.0.0.1:8202/health
- http://127.0.0.1:8202/

### Public URL options

1. **Preferred:** DNS `sateye-preview.xdgen.com` → host `zhzh`, reverse-proxy to `127.0.0.1:8202`, TLS via Dokploy/Caddy/Nginx/Cloudflare.  
2. **If DNS cannot be changed yet:** use SSH tunnel  
   `ssh -L 8202:127.0.0.1:8202 user@zhzh` then open http://127.0.0.1:8202  
3. **Dokploy alternative:** create a **new** Dokploy app/project (not `sateye-fz2ic4`), compose file = `docker-compose.preview.yml`, domain = `sateye-preview.xdgen.com`.

### Hard safety rules

1. Never attach production PostgreSQL / Redis / upload / cache volumes.  
2. Never run migrations against production DB.  
3. Never reuse production admin password / `SECRET_KEY`.  
4. Never redeploy or recreate `sateye-fz2ic4` for preview.  
5. No automatic production deploy from this preview work.

---

## 4) What this agent cannot do from the cloud VM

- No Docker daemon in the Cursor agent environment → preview containers were **not** started here.  
- No SSH to `zhzh` / Dokploy → DNS and public HTTPS must be finished on your server.  
- Production remains unchanged until you explicitly approve a production deploy.
