#!/usr/bin/env bash
# Read-only Ubuntu security audit helper (default).
# Token rotation and rollback touch only /etc/serverbackup/.
# Never stops Nginx, PHP-FPM, or MariaDB. Never walks the entire disk.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
  echo '{"ok": false, "error": "python3 is required"}' >&2
  exit 1
fi
PAYLOAD="$("$PYTHON" - <<'PY'
import json, os, sys, tempfile
raw = sys.stdin.read() or "{}"
data = json.loads(raw)
fd, path = tempfile.mkstemp(prefix="serverbackup-sec-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
print(path)
PY
)"
trap 'rm -f "$PAYLOAD"' EXIT
exec "$PYTHON" "$SCRIPT_DIR/security_audit.py" "$PAYLOAD"
