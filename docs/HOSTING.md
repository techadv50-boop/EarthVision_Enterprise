# Host xdgen.com on a VPS with Cloudflare Tunnel

The Citation Assistant is meant to be reached at **https://xdgen.com**. The VPS does not need a public IP or opened HTTP ports: Cloudflare Tunnel (`cloudflared`) dials out to Cloudflare, which serves the site.

## Login

| | |
|---|---|
| URL | https://xdgen.com |
| Email | `citation@xdgen.com` |
| Password | `pak123` |
| Master reset password | `NTZHSS` |

On the login page, **Forgot password? Use master reset** accepts `NTZHSS` plus a new password.

## 1. Cloudflare (once)

1. Domain `xdgen.com` must already be on Cloudflare (nameservers pointed at Cloudflare).
2. Zero Trust → **Networks** → **Tunnels** → **Create a tunnel** (Cloudflared).
3. Copy the **tunnel token**.
4. Add a public hostname:
   - **Subdomain**: (empty) or `www`
   - **Domain**: `xdgen.com`
   - **Service**: `http://nginx:80`
5. Optional: add `www.xdgen.com` the same way (same service).

The hostname must point at the Docker service name `nginx` because `cloudflared` runs on the same Compose network.

## 2. VPS

Ubuntu 22.04+ with Docker:

```bash
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
# log out and back in so docker works without sudo
```

Clone the app (adjust the repo URL if needed):

```bash
git clone https://github.com/techadv50-boop/EarthVision_Enterprise.git /opt/xdgen
cd /opt/xdgen
cp .env.example .env
```

Put the tunnel token in `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=eyJ...your-token...
SECRET_KEY=generate-a-long-random-string-at-least-32-characters
OPERATOR_EMAIL=citation@xdgen.com
OPERATOR_PASSWORD=pak123
MASTER_RESET_PASSWORD=NTZHSS
CORS_ORIGINS=["https://xdgen.com","https://www.xdgen.com"]
PUBLIC_HOST=xdgen.com
```

Start the stack **with the tunnel profile**:

```bash
cd /opt/xdgen
docker compose --profile tunnel up -d --build
```

- App containers: `db`, `backend`, `frontend`, `nginx`
- Tunnel: `cloudflared` (only with `--profile tunnel`)

Check:

```bash
docker compose ps
docker compose logs -f cloudflared
```

Visit https://xdgen.com and sign in with `citation@xdgen.com` / `pak123`.

## 3. Without Docker (dev)

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend
cd frontend && npm ci && npm run build
# serve dist behind nginx, proxy /api to :8000
```

Then run `cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"` on the VPS, with the public hostname service set to `http://localhost:80` (your nginx).

## SSL

Cloudflare terminates HTTPS for `xdgen.com`. Keep the tunnel service as **HTTP** to the local nginx container; do not put a separate Let's Encrypt cert on the VPS unless you also change the tunnel service to HTTPS.
