#!/usr/bin/env bash
# journal50.drxdhr.store currently shows the default nginx page.
# Serve the 50sea journal on that hostname instead.
set -u
echo "START host=$(hostname) user=$(id -un)"
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo."
  exit 1
fi

systemctl disable --now journal50-origin-proxy.service >/dev/null 2>&1 || true

is_journal() {
  printf '%s' "$1" | grep -q 'Open Journal Systems'
}

echo "--- local listeners ---"
ss -ltnp | awk 'NR==1 || /:80 |:8087|:8187/' || true

body_of() {
  curl -sS -m 8 -H "Host: $2" "$1" 2>/dev/null || true
}

upstream=""
up_host_header="journal.50sea.com"
for spec in \
  "http://192.168.18.18:8087/|journal.50sea.com" \
  "http://127.0.0.1:8087/|journal.50sea.com" \
  "http://192.168.18.18/|journal.50sea.com" \
  "http://127.0.0.1/|journal.50sea.com"
do
  url=${spec%%|*}
  hdr=${spec#*|}
  body=$(body_of "$url" "$hdr")
  if printf '%s' "$body" | grep -q 'Welcome to nginx'; then
    kind=nginx-welcome
  elif is_journal "$body"; then
    kind=journal
  else
    kind=other
  fi
  echo "probe ${url} host=${hdr} -> ${kind}"
  if [ -z "$upstream" ] && [ "$kind" = journal ]; then
    upstream=$url
  fi
done

if [ -z "$upstream" ]; then
  echo "The 50sea journal did not answer on this machine or on 192.168.18.18."
  exit 1
fi
echo "upstream ${upstream}"

if command -v nginx >/dev/null 2>&1; then
  cat >/etc/nginx/sites-available/journal50.drxdhr.store <<EOF
server {
    listen 80;
    listen 127.0.0.1:8187;
    server_name journal50.drxdhr.store;
    client_max_body_size 64m;
    location / {
        proxy_pass ${upstream};
        proxy_http_version 1.1;
        proxy_set_header Host ${up_host_header};
        proxy_set_header X-Forwarded-Host journal50.drxdhr.store;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Accept-Encoding "";
        proxy_cookie_domain journal.50sea.com journal50.drxdhr.store;
        proxy_redirect https://journal.50sea.com/ https://journal50.drxdhr.store/;
        proxy_redirect http://journal.50sea.com/ https://journal50.drxdhr.store/;
        sub_filter_types text/html text/css application/javascript application/json;
        sub_filter 'https://journal.50sea.com' 'https://journal50.drxdhr.store';
        sub_filter 'http://journal.50sea.com' 'https://journal50.drxdhr.store';
        sub_filter_once off;
        proxy_read_timeout 120s;
    }
}
EOF
  ln -sfn /etc/nginx/sites-available/journal50.drxdhr.store /etc/nginx/sites-enabled/journal50.drxdhr.store
  if nginx -t; then
    nginx -s reload || systemctl reload nginx
    echo "nginx reloaded"
  else
    echo "nginx rejected the journal site; removed it"
    rm -f /etc/nginx/sites-enabled/journal50.drxdhr.store
    nginx -t >/dev/null 2>&1 || true
    exit 1
  fi
else
  echo "nginx is not installed; forwarding port 8187 to the journal"
  install -d /usr/local/sbin
  cat >/usr/local/sbin/journal50-origin-proxy.py <<PY
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

UPSTREAM = os.environ["UPSTREAM"].rstrip("/")
HOST = os.environ.get("UP_HOST", "journal.50sea.com")

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def proxy(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = self.rfile.read(length) if length else None
        headers = {}
        for key, value in self.headers.items():
            if key.lower() in ("host", "content-length", "transfer-encoding", "connection", "accept-encoding"):
                continue
            headers[key] = value
        headers["Host"] = HOST
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-Host"] = "journal50.drxdhr.store"
        request = urllib.request.Request(UPSTREAM + self.path, data=payload, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:
            response = exc
        data = response.read()
        data = data.replace(b"https://journal.50sea.com", b"https://journal50.drxdhr.store")
        data = data.replace(b"http://journal.50sea.com", b"https://journal50.drxdhr.store")
        self.send_response(response.status)
        for key, value in response.headers.items():
            low = key.lower()
            if low in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                continue
            if low == "location" or low == "set-cookie":
                value = value.replace("https://journal.50sea.com", "https://journal50.drxdhr.store")
                value = value.replace("http://journal.50sea.com", "https://journal50.drxdhr.store")
                value = value.replace("domain=journal.50sea.com", "domain=journal50.drxdhr.store")
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self): self.proxy()
    def do_POST(self): self.proxy()
    def do_HEAD(self): self.proxy()
    def do_PUT(self): self.proxy()
    def do_DELETE(self): self.proxy()

ThreadingHTTPServer(("127.0.0.1", 8187), Handler).serve_forever()
PY
  chmod 755 /usr/local/sbin/journal50-origin-proxy.py
  cat >/etc/systemd/system/journal50-origin-proxy.service <<EOF
[Unit]
Description=Serve the 50sea journal on journal50.drxdhr.store
After=network-online.target
[Service]
Environment=UPSTREAM=${upstream}
Environment=UP_HOST=${up_host_header}
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

public=$(curl -sS -m 20 https://journal50.drxdhr.store/ || true)
if printf '%s' "$public" | grep -q 'Open Journal Systems'; then
  echo "PUBLIC journal"
elif printf '%s' "$public" | grep -q 'Welcome to nginx'; then
  echo "PUBLIC still the nginx welcome page"
  exit 1
else
  echo "PUBLIC unexpected"
  printf '%s\n' "$public" | head -c 180
  echo
  exit 1
fi
