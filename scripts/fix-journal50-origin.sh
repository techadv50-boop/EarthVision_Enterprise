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
import sys
import urllib.error
import urllib.request

UPSTREAM = "http://192.168.18.18"
HOST = "journal.50sea.com"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

OPENER = urllib.request.build_opener(NoRedirect)

OLD_HOST = "journal.50sea.com"
NEW_HOST = "journal50.drxdhr.store"

def rewrite(value):
    # OJS prints the submissions API address with json_encode, which turns
    # https://journal.50sea.com into https:\/\/journal.50sea.com. All Active
    # and Archives load from that address. A plain URL replace leaves it
    # pointing at the original site, so the browser calls it without this
    # site's session and the list stays empty.
    value = value.replace("http://" + OLD_HOST, "https://" + NEW_HOST)
    value = value.replace("http:\\/\\/" + OLD_HOST, "https:\\/\\/" + NEW_HOST)
    value = value.replace("http%3A%2F%2F" + OLD_HOST, "https%3A%2F%2F" + NEW_HOST)
    value = value.replace("http%3a%2f%2f" + OLD_HOST, "https%3A%2F%2F" + NEW_HOST)
    return value.replace(OLD_HOST, NEW_HOST)

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def read_body(self):
        # Grid and API saves can arrive without Content-Length. Read that
        # body too, or the journal receives an empty request.
        transfer = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in transfer:
            chunks = []
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                size_token = line.split(b";", 1)[0].strip()
                try:
                    size = int(size_token, 16)
                except ValueError:
                    break
                if size == 0:
                    while True:
                        trailer = self.rfile.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0:
            length = 0
        return self.rfile.read(length) if length else b""

    def proxy(self):
        payload = self.read_body()
        if not payload and self.command not in ("POST", "PUT", "PATCH", "DELETE"):
            payload = None
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
            if OLD_HOST in value:
                value = rewrite(value)
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        if "/api/" in self.path.split("?", 1)[0]:
            sys.stderr.write("%s %s %s\n" % (self.command, self.path.split("?", 1)[0][:180], response.status))

    def do_GET(self):
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_HEAD(self):
        self.proxy()

    def do_PUT(self):
        self.proxy()

    def do_PATCH(self):
        self.proxy()

    def do_DELETE(self):
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8187), Handler).serve_forever()
PY
chmod 755 /usr/local/sbin/journal50-origin-proxy.py
python3 - << 'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("journal50_proxy", "/usr/local/sbin/journal50-origin-proxy.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
samples = [
    'https:\\/\\/journal.50sea.com\\/index.php\\/IJIST\\/api\\/v1\\/_submissions',
    "https://journal.50sea.com/index.php/IJIST",
    "http://journal.50sea.com/index.php/IJIST",
    "https%3A%2F%2Fjournal.50sea.com%2Findex.php%2FIJIST",
    "domain=journal.50sea.com",
]
for sample in samples:
    out = mod.rewrite(sample)
    if "journal.50sea.com" in out or "journal50.drxdhr.store" not in out:
        raise SystemExit("REWRITE failed: %s -> %s" % (sample, out))
    if mod.rewrite(out) != out:
        raise SystemExit("REWRITE not stable: %s" % out)
print("REWRITE ok")
PY
if [ "$?" -ne 0 ]; then
  echo "REWRITE check failed"
  exit 1
fi

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
echo "DONE. Hard-refresh the submissions page, then open All Active and Archives."
