#!/usr/bin/env bash
# Build a portable zip package (source + Windows launchers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
NAME="WebCrawlerEnterprise-Portable"
STAGE="$OUT/$NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE"

# Copy runtime files
cp -R "$ROOT/webcrawler" "$STAGE/webcrawler"
cp -R "$ROOT/scripts" "$STAGE/scripts"
cp "$ROOT/main.py" "$STAGE/"
cp "$ROOT/requirements.txt" "$STAGE/"
cp "$ROOT/pyproject.toml" "$STAGE/"
cp "$ROOT/README.md" "$STAGE/"
cp "$ROOT/Setup.bat" "$STAGE/"
cp "$ROOT/Run_WebCrawlerEnterprise.bat" "$STAGE/"
cp "$ROOT/START_HERE.txt" "$STAGE/"
cp "$ROOT/README_STANDALONE.txt" "$STAGE/" 2>/dev/null || true
cp "$ROOT/STABLE_RUN.txt" "$STAGE/" 2>/dev/null || true
cp "$ROOT/webcrawler_enterprise.spec" "$STAGE/" 2>/dev/null || true

# Optional tests for developers
mkdir -p "$STAGE/tests"
cp -R "$ROOT/tests/." "$STAGE/tests/" 2>/dev/null || true

# Clean caches
find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGE" -type f -name "*.pyc" -delete

mkdir -p "$OUT"
ZIP="$OUT/${NAME}.zip"
rm -f "$ZIP"
(cd "$OUT" && zip -r -q "$(basename "$ZIP")" "$NAME")
echo "Created: $ZIP"
ls -lh "$ZIP"
