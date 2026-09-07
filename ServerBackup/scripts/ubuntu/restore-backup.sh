#!/usr/bin/env bash
# Ubuntu restore helper. Never runs without a JSON payload from the Windows app.
# Does not restart Nginx. Creates safety copies before destructive copies.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
  echo "python3 is required" >&2
  exit 1
fi
PAYLOAD="$("$PYTHON" - <<'PY'
import json, os, sys, tempfile
raw = sys.stdin.read() or "{}"
data = json.loads(raw)
fd, path = tempfile.mkstemp(prefix="serverbackup-restore-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
print(path)
PY
)"
trap 'rm -f "$PAYLOAD"' EXIT
exec "$PYTHON" "$SCRIPT_DIR/restore_backup.py" "$PAYLOAD"
