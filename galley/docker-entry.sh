#!/bin/sh
/opt/venv/bin/uvicorn app:app --app-dir /app/server --host 127.0.0.1 --port 8787 &
exec nginx -g "daemon off;"
