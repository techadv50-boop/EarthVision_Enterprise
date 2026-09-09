#!/usr/bin/env bash
# Ubuntu restore helper. Never runs without a JSON payload from the Windows app.
# Does not restart Nginx. Creates safety copies before destructive copies.
# JSON is read from stdin the same way as prepare-backup.sh (no heredoc).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
  echo "python3 is required" >&2
  exit 1
fi

PAYLOAD="$("$PYTHON" -c 'import json, os, sys, tempfile
raw = sys.stdin.read() or "{}"
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print("INVALID_JSON", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(data, dict):
    print("INVALID_JSON", file=sys.stderr)
    raise SystemExit(2)
fd, path = tempfile.mkstemp(prefix="serverbackup-restore-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
print(path)
')"

cleanup_payload() {
  rm -f "$PAYLOAD" 2>/dev/null || true
}
trap cleanup_payload EXIT
exec "$PYTHON" "$SCRIPT_DIR/restore_backup.py" "$PAYLOAD"
