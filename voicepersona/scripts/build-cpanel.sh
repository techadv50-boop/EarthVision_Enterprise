#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/deploy/dist"

echo "Building frontend…"
cd "$ROOT/frontend"
npm install
npm run build

echo "Assembling cPanel package…"
rm -rf "$DIST"
mkdir -p "$DIST/api" "$DIST/data/personas" "$DIST/data/samples"

cp -R "$ROOT/frontend/dist/." "$DIST/"
cp "$ROOT/public/.htaccess" "$DIST/.htaccess"
cp "$ROOT/api/"*.php "$DIST/api/"
cp "$ROOT/api/.htaccess" "$DIST/api/.htaccess"

# Protect raw data from direct web listing where possible
cat > "$DIST/data/.htaccess" <<'EOF'
Options -Indexes
# Deny direct download of persona JSON; audio is served via API.
<FilesMatch "\.json$">
  Require all denied
</FilesMatch>
EOF

touch "$DIST/data/personas/.gitkeep" "$DIST/data/samples/.gitkeep"

echo "Done: $DIST"
echo "Upload the CONTENTS of deploy/dist/ into public_html on cPanel."
