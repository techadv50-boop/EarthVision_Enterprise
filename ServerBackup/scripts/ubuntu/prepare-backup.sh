#!/usr/bin/env bash
# Ubuntu backup preparation helper.
# Read-only against websites, Nginx, and MariaDB data files.
# Never stops Nginx, PHP-FPM, or MariaDB.
# JSON is read from stdin. Output includes a JSON object on stdout.
set -euo pipefail

umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SERVERBACKUP_LIB="${SERVERBACKUP_LIB:-$SCRIPT_DIR}"
PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
  echo '{"ok": false, "error": "python3 is required"}' >&2
  exit 1
fi

# Parse stdin JSON into a temp file. python -c keeps the wrapper stdin
# (the Windows JSON payload). `python3 - <<'PY'` would replace stdin with
# the heredoc, so the payload became {} and the allowlist rejected it.
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
fd, path = tempfile.mkstemp(prefix="serverbackup-payload-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
print(path)
')"

cleanup_payload() {
  rm -f "$PAYLOAD" 2>/dev/null || true
}
trap cleanup_payload EXIT

ACTION="$("$PYTHON" - "$PAYLOAD" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("action") or "")
PY
)"

ALLOWED="check discover-databases backup cleanup dry-run"
if [[ " $ALLOWED " != *" $ACTION "* ]]; then
  echo "{\"ok\": false, \"error\": \"action not allowed\"}" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/prepare_backup.py" "$PAYLOAD"
