#!/usr/bin/env bash
# Repair the Cloudflare Tunnel 502 for https://journal50.drxdhr.store/
# The public body "error code: 502" is cloudflared failing to dial its origin.
# This only starts a stopped journal container, or listens on the refused
# loopback port and forwards it to the live OJS backend. It does not print
# tokens, env files, or database passwords.
set -u
HOST="journal50.drxdhr.store"
LOG=/tmp/journal50-cloudflared.log
BODY=/tmp/journal50-body.txt
: >"$LOG"

say() { printf '%s\n' "$*"; }

public_code() {
  curl -sS -m 20 -o "$BODY" -w '%{http_code}' "https://${HOST}/" 2>/tmp/journal50-curl.err || echo ERR
}

redact() {
  sed -E 's/(--token[= ]+)[^ ]+/\1REDACTED/g; s/(eyJ[A-Za-z0-9_-]{8,})/REDACTED/g'
}

say "host=$(hostname) user=$(id -un) date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code=$(public_code)
snip=$(head -c 80 "$BODY" 2>/dev/null | tr '\n' ' ')
say "before ${code} ${snip}"
if [ "$code" != "502" ] || ! grep -q 'error code: 502' "$BODY" 2>/dev/null; then
  say "public response is not the cloudflared origin failure; no changes made"
  exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

say "--- journal containers ---"
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}} | {{.Status}} | {{.Ports}}' | grep -Ei 'journal|cloudflared|nginx' || true
  # Start a stopped OJS container only. Do not recreate it.
  while read -r name state; do
    [ -n "${name:-}" ] || continue
    state=$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]')
    case "$state" in
      exited*|created*|dead*)
        say "starting stopped container ${name}"
        docker start "$name" || say "could not start ${name}"
        ;;
    esac
  done < <(docker ps -a --filter name=journal50seacom --format '{{.Names}} {{.Status}}' | awk '{print $1, $2}')
fi

# Reproduce once so the connector logs this hostname.
curl -sS -m 15 -o /dev/null "https://${HOST}/" || true
sleep 2

if command -v journalctl >/dev/null 2>&1; then
  journalctl -u cloudflared --since '5 min ago' --no-pager 2>/dev/null | redact >>"$LOG" || true
  journalctl -u 'cloudflared*' --since '5 min ago' --no-pager 2>/dev/null | redact >>"$LOG" || true
fi
if command -v docker >/dev/null 2>&1; then
  while read -r name; do
    [ -n "$name" ] || continue
    say "logs from ${name}"
    docker logs --since 5m "$name" 2>&1 | redact >>"$LOG" || true
  done < <(docker ps -a --format '{{.Names}} {{.Image}}' | awk 'BEGIN{IGNORECASE=1} /cloudflared/ {print $1}')
fi

say "--- origin errors ---"
grep -Ei 'journal50|connection refused|unable to reach|origin' "$LOG" | tail -40 || true

origin=$(grep -Ei 'journal50\.drxdhr\.store' "$LOG" | grep -Eo 'dial tcp [^ ]+:[0-9]+' | tail -1 || true)
service=$(grep -Ei 'journal50\.drxdhr\.store' "$LOG" | grep -Eo 'https?://[^ "]+' | grep -v "$HOST" | tail -1 || true)
say "parsed_dial=${origin:-none} parsed_service=${service:-none}"

port=""
if [ -n "$origin" ]; then
  port=${origin##*:}
fi
if [ -z "$port" ] && [ -n "$service" ]; then
  port=$(printf '%s' "$service" | sed -n 's#.*:\([0-9][0-9]*\).*#\1#p')
  [ -n "$port" ] || port=80
fi

if [ -z "$port" ]; then
  say "cloudflared log did not name ${HOST} and a refused port; no proxy added"
  exit 0
fi

# Confirm the live journal answers before forwarding anything to it.
journal_code=$(curl -sS -m 8 -o /tmp/journal50-ojs.txt -w '%{http_code}' -H 'Host: journal.50sea.com' http://127.0.0.1:8087/ || echo ERR)
say "ojs_8087=${journal_code}"
if [ "$journal_code" != "200" ] && [ "$journal_code" != "301" ] && [ "$journal_code" != "302" ]; then
  say "OJS on 127.0.0.1:8087 is not answering; not attaching a new proxy"
  exit 0
fi

if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"; then
  say "port ${port} is already listening on this host; not binding over it"
else
  say "port ${port} is free on the host"
fi

# Prefer the cloudflared network namespace when the tunnel runs in Docker,
# because its localhost is not the host's localhost.
cf_name=$(docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /cloudflared/ {print $1; exit}')
cf_net=""
if [ -n "$cf_name" ]; then
  cf_net=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$cf_name" 2>/dev/null || true)
  say "cloudflared=${cf_name} network=${cf_net}"
fi

write_nginx() {
  local dest=$1 upstream=$2
  cat >"$dest" <<EOF
events { worker_connections 128; }
http {
  server {
    listen 127.0.0.1:${port};
    listen [::1]:${port};
    server_name ${HOST};
    client_max_body_size 64m;
    location / {
      proxy_pass ${upstream};
      proxy_http_version 1.1;
      proxy_set_header Host \$host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
      proxy_read_timeout 120s;
    }
  }
}
EOF
}

if [ -n "$cf_name" ] && [ "$cf_net" != "host" ]; then
  gateway=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $v.Gateway}}{{end}}' "$cf_name" | awk 'NF{print; exit}')
  [ -n "$gateway" ] || gateway=host.docker.internal
  say "sidecar upstream gateway=${gateway}"
  conf=/tmp/journal50-sidecar-nginx.conf
  write_nginx "$conf" "http://${gateway}:8087"
  if docker ps --format '{{.Names}}' | grep -qx journal50-origin-proxy; then
    say "sidecar already running"
  else
    docker rm -f journal50-origin-proxy >/dev/null 2>&1 || true
    if docker run -d --name journal50-origin-proxy --restart unless-stopped \
      --network "container:${cf_name}" \
      -v "$conf:/etc/nginx/nginx.conf:ro" \
      nginx:alpine; then
      say "started sidecar on cloudflared loopback :${port}"
    else
      say "sidecar failed"
    fi
  fi
else
  conf=/etc/nginx/sites-available/journal50.drxdhr.store
  if [ -d /etc/nginx/sites-available ] && command -v nginx >/dev/null 2>&1; then
    listening=0
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"; then
      listening=1
    fi
    if [ "$listening" -eq 0 ] && [ ! -f "$conf" ]; then
      $SUDO tee "$conf" >/dev/null <<EOF
server {
    listen 127.0.0.1:${port};
    listen [::1]:${port};
    server_name ${HOST};
    client_max_body_size 64m;
    location / {
        proxy_pass http://127.0.0.1:8087;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
EOF
      $SUDO ln -sfn "$conf" /etc/nginx/sites-enabled/journal50.drxdhr.store
    elif [ "$listening" -eq 1 ]; then
      site=$(grep -R -l 'journal.50sea.com' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1 || true)
      if [ -n "$site" ] && ! grep -q "$HOST" "$site"; then
        say "adding ${HOST} to ${site}"
        $SUDO cp -a "$site" /tmp/journal50-nginx-site.bak
        $SUDO sed -i "s/server_name journal.50sea.com;/server_name journal.50sea.com ${HOST};/" "$site"
      fi
    fi
    if $SUDO nginx -t; then
      $SUDO nginx -s reload || $SUDO systemctl reload nginx || true
      say "nginx reloaded for ${HOST}"
    else
      say "nginx config test failed; restored the previous site"
      $SUDO rm -f /etc/nginx/sites-enabled/journal50.drxdhr.store "$conf"
      if [ -f /tmp/journal50-nginx-site.bak ] && [ -n "${site:-}" ]; then
        $SUDO cp -a /tmp/journal50-nginx-site.bak "$site"
      fi
      $SUDO nginx -t >/dev/null 2>&1 || true
    fi
  else
    say "no host nginx to attach; origin port was ${port}"
  fi
fi

sleep 2
code=$(public_code)
snip=$(head -c 80 "$BODY" 2>/dev/null | tr '\n' ' ')
say "after ${code} ${snip}"
if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
  exit 0
fi
exit 1
