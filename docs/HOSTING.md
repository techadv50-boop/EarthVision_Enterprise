# Host citation.xdgen.com on a VPS with Cloudflare Tunnel

The Citation Assistant is meant to be reached at **https://citation.xdgen.com**. Keep **https://xdgen.com** as your main website. The VPS does not need a public IP or opened HTTP ports: Cloudflare Tunnel (`cloudflared`) dials out to Cloudflare, which serves the app.

## Login

| | |
|---|---|
| URL | https://citation.xdgen.com |
| Email | `citation@xdgen.com` |
| Password | `pak123` |
| Master reset password | `NTZHSS` |

On the login page, **Forgot password? Use master reset** accepts `NTZHSS` plus a new password.

## 1. Cloudflare (once)

1. Domain `xdgen.com` must already be on Cloudflare (nameservers pointed at Cloudflare).
2. Zero Trust → **Networks** → **Tunnels** → **Create a tunnel** (Cloudflared).
3. Copy the **tunnel token**.
4. Add a public hostname for this app:
   - **Subdomain**: `citation`
   - **Domain**: `xdgen.com`
   - **Type**: HTTP
   - **URL**: `nginx:80` (Docker) or `localhost:8080` if nginx is published on the host
5. Leave apex `xdgen.com` pointed at your main website (Pages, origin, or a different tunnel hostname). Do not route `xdgen.com` to this stack unless you want the citation app to replace the main site.

Cloudflare creates the `citation` DNS CNAME automatically when you save the public hostname.

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
CORS_ORIGINS=["https://citation.xdgen.com","https://xdgen.com","https://www.xdgen.com"]
PUBLIC_HOST=citation.xdgen.com
```

Start the stack **with the tunnel profile**:

```bash
cd /opt/xdgen
docker compose --profile tunnel up -d --build
```

Check:

```bash
docker compose ps
docker compose logs -f cloudflared
```

Visit https://citation.xdgen.com and sign in with `citation@xdgen.com` / `pak123`.

## SSL

Cloudflare terminates HTTPS for `citation.xdgen.com`. Keep the tunnel service as **HTTP** to nginx; you do not need Let's Encrypt on the VPS.
