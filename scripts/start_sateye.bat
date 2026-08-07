@echo off
REM SAT EYE offline launcher for Windows
setlocal
cd /d %~dp0\..

if not exist .venv (
  echo Run scripts\install_sateye.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat
set OFFLINE_MODE=true
set APP_NAME=SAT EYE

start "SAT EYE API" cmd /c "cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir ."
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
