@echo off
REM SAT EYE offline installer for Windows
setlocal
cd /d %~dp0\..

echo ========================================
echo   SAT EYE — Offline Earth Observation
echo ========================================

if not exist .env copy .env.example .env

python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt

cd frontend
call npm install
cd ..

echo.
echo Installation complete.
echo Start with: scripts\start_sateye.bat
echo Then open http://127.0.0.1:5173
