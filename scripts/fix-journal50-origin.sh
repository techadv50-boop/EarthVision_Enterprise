#!/usr/bin/env bash
# cloudflared on raza dials 127.0.0.1:8187 for journal50.drxdhr.store.
# The journal answers at http://192.168.18.18/ when Host is journal.50sea.com.
set -u
echo "START host=$(hostname) user=$(id -un)"
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo."
  exit 1
fi

# Port 8187 must belong to this proxy, not an nginx listener.
if [ -f /etc/nginx/sites-available/journal50.drxdhr.store ]; then
  sed -i '/listen 127\.0\.0\.1:8187;/d' /etc/nginx/sites-available/journal50.drxdhr.store
  nginx -t && nginx -s reload || true
fi

install -d /usr/local/sbin
cat >/usr/local/sbin/journal50-origin-proxy.py <<'PY'
#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

UPSTREAM = "http://192.168.18.18"
HOST = "journal.50sea.com"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

OPENER = urllib.request.build_opener(NoRedirect)

def rewrite(value):
    return (
        value.replace("https://journal.50sea.com", "https://journal50.drxdhr.store")
        .replace("http://journal.50sea.com", "https://journal50.drxdhr.store")
        .replace("domain=journal.50sea.com", "domain=journal50.drxdhr.store")
    )

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def proxy(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = self.rfile.read(length) if length else None
        headers = {}
        for key, value in self.headers.items():
            # The journal rejects the tunnel hostname. Ask for it as journal.50sea.com
            # and drop forwarded-host headers that would override that.
            if key.lower() in (
                "host", "content-length", "transfer-encoding", "connection",
                "accept-encoding", "x-forwarded-host", "x-forwarded-server",
                "x-forwarded-proto", "forwarded",
            ):
                continue
            headers[key] = value
        headers["Host"] = HOST
        request = urllib.request.Request(UPSTREAM + self.path, data=payload, headers=headers, method=self.command)
        try:
            response = OPENER.open(request, timeout=120)
        except urllib.error.HTTPError as exc:
            response = exc
        data = response.read()
        kind = response.headers.get("Content-Type", "")
        if any(token in kind for token in ("text", "javascript", "json")):
            data = rewrite(data.decode("utf-8", "replace")).encode("utf-8")
        self.send_response(response.status)
        for key, value in response.headers.items():
            low = key.lower()
            if low in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                continue
            if low in ("location", "set-cookie"):
                value = rewrite(value)
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_HEAD(self):
        self.proxy()

ThreadingHTTPServer(("127.0.0.1", 8187), Handler).serve_forever()
PY
chmod 755 /usr/local/sbin/journal50-origin-proxy.py

cat >/etc/systemd/system/journal50-origin-proxy.service <<'EOF'
[Unit]
Description=Serve the 50sea journal for journal50.drxdhr.store
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/sbin/journal50-origin-proxy.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now journal50-origin-proxy.service
systemctl restart journal50-origin-proxy.service
sleep 1
systemctl is-active journal50-origin-proxy.service || systemctl --no-pager --full status journal50-origin-proxy.service | head -20
ss -ltnp | grep 8187 || echo "8187 closed"

echo -n "LOCAL "
curl -sS -m 12 -o /var/lib/journal50-local.html -w '%{http_code} ' -H 'Host: journal50.drxdhr.store' http://127.0.0.1:8187/ || echo ERR
grep -o 'Open Journal Systems\|Welcome to nginx' /var/lib/journal50-local.html | head -1 || true
echo
echo -n "PUBLIC "
curl -sS -m 20 -o /var/lib/journal50-public.html -w '%{http_code} ' https://journal50.drxdhr.store/ || echo ERR
grep -o 'Open Journal Systems\|Welcome to nginx\|error code' /var/lib/journal50-public.html | head -1 || true
echo
