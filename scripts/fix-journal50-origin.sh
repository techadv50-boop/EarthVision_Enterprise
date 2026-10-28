#!/usr/bin/env bash
# Open 127.0.0.1:8187 on raza. cloudflared dials that port for journal50.drxdhr.store.
# Paste with: sudo bash -s <<'EOF' ... EOF
set -u
echo "START host=$(hostname) user=$(id -un)"
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo."
  exit 1
fi

port=8187
port_open() { ss -ltn | awk '{print $4}' | grep -Eq "(^|:)${1}$"; }

if command -v docker >/dev/null 2>&1; then
  echo "--- docker ---"
  docker ps -a --format '{{.Names}} | {{.Status}} | {{.Ports}}' | head -60 || true
  for id in $(docker ps -aq); do
    binding=$(docker inspect -f '{{json .HostConfig.PortBindings}} {{.Name}} {{.State.Status}}' "$id" 2>/dev/null || true)
    printf '%s\n' "$binding" | grep -q "\"${port}/tcp\"" || continue
    echo "binds ${port}: ${binding}"
    case "$binding" in
      *running) ;;
      *) docker start "$id" || echo "could not start $id" ;;
    esac
  done
else
  echo "docker is not installed"
fi

sleep 1
if port_open "$port"; then
  echo "port ${port} is open"
else
  echo "port ${port} is closed; choosing an upstream"
  upstream=""
  for spec in \
    "127.0.0.1:8087" \
    "192.168.18.18:8087" \
    "192.168.18.18:80"
  do
    code=$(curl -sS -m 6 -o /dev/null -w '%{http_code}' -H 'Host: journal.50sea.com' "http://${spec}/" || echo ERR)
    echo "probe ${spec} -> ${code}"
    case "$code" in
      200|301|302|303) upstream=$spec; break ;;
    esac
  done
  if [ -z "$upstream" ]; then
    echo "no journal answered; port ${port} left closed"
    exit 1
  fi
  up_host=${upstream%%:*}
  up_port=${upstream##*:}
  echo "forward 127.0.0.1:${port} -> ${up_host}:${up_port}"
  install -d /usr/local/sbin
  cat >/usr/local/sbin/journal50-origin-proxy.py <<'PY'
import os, socket, threading
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
    a = threading.Thread(target=pipe, args=(client, upstream), daemon=True)
    b = threading.Thread(target=pipe, args=(upstream, client), daemon=True)
    a.start(); b.start(); a.join(); b.join()
    client.close(); upstream.close()

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", listen_port))
server.listen(64)
while True:
    client, _ = server.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
PY
  chmod 755 /usr/local/sbin/journal50-origin-proxy.py
  cat >/etc/systemd/system/journal50-origin-proxy.service <<EOF
[Unit]
Description=Forward journal50.drxdhr.store to the live journal
After=network-online.target

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
  systemctl is-active journal50-origin-proxy.service || true
fi

code=$(curl -sS -m 20 -o /var/lib/journal50-body.txt -w '%{http_code}' https://journal50.drxdhr.store/ || echo ERR)
echo "PUBLIC ${code} $(head -c 60 /var/lib/journal50-body.txt 2>/dev/null | tr '\n' ' ')"
case "$code" in
  200|301|302|303) exit 0 ;;
  *) exit 1 ;;
esac
