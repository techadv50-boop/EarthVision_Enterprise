@echo off
REM SAT EYE server launcher for Windows (field access on LAN)
setlocal
cd /d %~dp0\..

if not exist .venv (
  echo Run scripts\install_sateye.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat
set OFFLINE_MODE=true
set REQUIRE_LOGIN=true
set CORS_ALLOW_ALL=true
set MASTER_RESET_CODE=NTZHSS
set APP_NAME=SAT EYE
set SERVER_HOST=0.0.0.0
set SERVER_PORT=8000

echo Starting SAT EYE API on 0.0.0.0:8000 ...
start "SAT EYE API" cmd /c "cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir ."

echo Starting SAT EYE UI on 0.0.0.0:5173 ...
echo Field clients: http://YOUR-SERVER-IP:5173
echo Admin login: admin / Admin@123456
echo Master password-reset code: NTZHSS
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
