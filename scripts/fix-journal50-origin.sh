#!/usr/bin/env bash
# Repair https://journal50.drxdhr.store/ when cloudflared is up but its
# origin port is closed. On raza that port is 127.0.0.1:8187.
# Run as root: curl -fsSL <this-url> | sudo bash
set -u
HOST="journal50.drxdhr.store"
LOG=/tmp/journal50-cloudflared.log
BODY=/tmp/journal50-body.txt

say() { printf '%s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  say "Docker on this host needs root. Re-run with: curl -fsSL <script-url> | sudo bash"
  exit 1
fi

public_code() {
  curl -sS -m 20 -o "$BODY" -w '%{http_code}' "https://${HOST}/" 2>/tmp/journal50-curl.err || echo ERR
}

redact() {
  sed -E 's/(--token[= ]+)[^ ]+/\1REDACTED/g; s/(eyJ[A-Za-z0-9_-]{8,})/REDACTED/g'
}

port_open() {
  ss -ltn | awk '{print $4}' | grep -Eq "(^|:)${1}$"
}

http_code() {
  # $1 url, optional $2 Host header
  if [ -n "${2:-}" ]; then
    curl -sS -m 8 -o /tmp/journal50-up.txt -w '%{http_code}' -H "Host: $2" "$1" || echo ERR
  else
    curl -sS -m 8 -o /tmp/journal50-up.txt -w '%{http_code}' "$1" || echo ERR
  fi
}

good_code() {
  case "$1" in
    200|301|302|303) return 0 ;;
    *) return 1 ;;
  esac
}

say "host=$(hostname) user=$(id -un) date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code=$(public_code)
snip=$(head -c 80 "$BODY" 2>/dev/null | tr '\n' ' ')
say "before ${code} ${snip}"
if [ "$code" != "502" ] || ! grep -q 'error code: 502' "$BODY" 2>/dev/null; then
  say "public response is not the cloudflared origin failure; no changes made"
  exit 0
fi

: >"$LOG"
journalctl -u cloudflared --since '15 min ago' --no-pager 2>/dev/null | redact >>"$LOG" || true
journalctl -u 'cloudflared*' --since '15 min ago' --no-pager 2>/dev/null | redact >>"$LOG" || true

origin=$(grep -F 'journal50.drxdhr.store' "$LOG" | grep -Eo 'dial tcp [^ ]+:[0-9]+' | tail -1 || true)
if [ -z "$origin" ]; then
  origin=$(grep -F 'originService=http://127.0.0.1:' "$LOG" | grep -Eo '127\.0\.0\.1:[0-9]+' | tail -1 || true)
  origin="dial tcp ${origin}"
fi
port=${origin##*:}
port=${port%%[^0-9]*}
say "parsed_dial=${origin:-none} port=${port:-none}"
if ! printf '%s' "$port" | grep -Eq '^[0-9]+$'; then
  say "cloudflared log did not name the refused port; no changes made"
  exit 1
fi

say "--- listeners ---"
ss -ltnp | head -80 || true

say "--- docker ---"
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}} | {{.Status}} | {{.Ports}}' | head -80 || true
  # Start stopped containers that are published on the refused port.
  while read -r id; do
    [ -n "$id" ] || continue
    binding=$(docker inspect -f '{{json .HostConfig.PortBindings}} {{.Name}} {{.State.Status}}' "$id" 2>/dev/null || true)
    printf '%s\n' "$binding" | grep -q "\"${port}/tcp\"" || continue
    name=$(printf '%s' "$binding" | awk '{print $(NF-1)}')
    state=$(printf '%s' "$binding" | awk '{print $NF}')
    say "container ${name} binds ${port}/tcp (${state})"
    case "$(printf '%s' "$state" | tr '[:upper:]' '[:lower:]')" in
      running) ;;
      *)
        say "starting ${name}"
        docker start "$id" || say "could not start ${name}"
        ;;
    esac
  done < <(docker ps -aq)
else
  say "docker is not installed"
fi

# Compose projects that publish this port.
if command -v docker >/dev/null 2>&1 && ! port_open "$port"; then
  while read -r file; do
    [ -n "$file" ] || continue
    dir=$(dirname "$file")
    say "compose mentions :${port} in ${file}"
    (cd "$dir" && docker compose up -d) || say "compose up failed in ${dir}"
  done < <(grep -R -l -E ":${port}\\b" /etc/dokploy /opt /home/zh /home/zhzh /etc/nginx /etc/systemd/system \
    --include='*.yml' --include='*.yaml' 2>/dev/null | head -20)
fi

sleep 2
if port_open "$port"; then
  local_code=$(http_code "http://127.0.0.1:${port}/" "$HOST")
  say "local :${port} -> ${local_code}"
else
  say "port ${port} is still closed; looking for the live journal"
  upstream=""
  for candidate in \
    "http://127.0.0.1:8087/|" \
    "http://127.0.0.1:80/|${HOST}" \
    "http://127.0.0.1:80/|journal.50sea.com" \
    "http://192.168.18.18:8087/|" \
    "http://192.168.18.18:80/|journal.50sea.com" \
    "http://192.168.18.18:8087/|journal.50sea.com"
  do
    url=${candidate%%|*}
    hdr=${candidate#*|}
    c=$(http_code "$url" "$hdr")
    say "probe ${url} host=${hdr:-default} -> ${c}"
    if good_code "$c"; then
      upstream=$url
      break
    fi
  done

  if [ -z "$upstream" ]; then
    say "no journal is answering on this host or on 192.168.18.18; left ${port} closed"
    exit 1
  fi

  # upstream is http://host:port/
  rest=${upstream#http://}
  rest=${rest%/}
  up_host=${rest%%:*}
  up_port=${rest##*:}
  if [ "$up_host" = "$up_port" ]; then
    up_port=80
  fi
  say "forwarding 127.0.0.1:${port} -> ${up_host}:${up_port}"

  install -d /usr/local/sbin
  cat >/usr/local/sbin/journal50-origin-proxy.py <<'PY'
#!/usr/bin/env python3
"""TCP proxy: cloudflared's loopback origin -> the live journal."""
import os
import socket
import threading

listen_port = int(os.environ["LISTEN_PORT"])
up_host = os.environ["UP_HOST"]
up_port = int(os.environ["UP_PORT"])


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock, how in ((src, socket.SHUT_RD), (dst, socket.SHUT_WR)):
            try:
                sock.shutdown(how)
            except OSError:
                pass


def handle(client):
    try:
        upstream = socket.create_connection((up_host, up_port), timeout=10)
    except OSError:
        client.close()
        return
    upstream.settimeout(None)
    left = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
    right = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
    left.start()
    right.start()
    left.join()
    right.join()
    client.close()
    upstream.close()


server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", listen_port))
server.listen(64)
while True:
    client, _addr = server.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
PY
  chmod 755 /usr/local/sbin/journal50-origin-proxy.py
  cat >/etc/systemd/system/journal50-origin-proxy.service <<EOF
[Unit]
Description=Forward journal50.drxdhr.store origin to the live journal
After=network-online.target
Wants=network-online.target

[Service]
Environment=LISTEN_PORT=${port}
Environment=UP_HOST=${up_host}
Environment=UP_PORT=${up_port}
ExecStart=/usr/bin/python3 /usr/local/sbin/journal50-origin-proxy.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now journal50-origin-proxy.service
  sleep 1
  systemctl --no-pager --full status journal50-origin-proxy.service | head -20 || true
  local_code=$(http_code "http://127.0.0.1:${port}/" "$HOST")
  say "local :${port} -> ${local_code}"
fi

sleep 2
code=$(public_code)
snip=$(head -c 100 "$BODY" 2>/dev/null | tr '\n' ' ')
say "after ${code} ${snip}"
if good_code "$code"; then
  exit 0
fi
exit 1
