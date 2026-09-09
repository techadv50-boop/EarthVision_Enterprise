@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  WebCrawler Enterprise - First-time Setup
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found on PATH.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo Make sure "Add python.exe to PATH" is checked.
  pause
  exit /b 1
)

echo [1/3] Installing Python packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package install failed.
  pause
  exit /b 1
)

echo.
echo [2/3] Installing Playwright Chromium browser...
python -m playwright install chromium
if errorlevel 1 (
  echo Playwright browser install failed.
  pause
  exit /b 1
)

echo.
echo [3/3] Setup complete.
echo.
echo Login defaults:
echo   Username: admin
echo   Password: admin  ^(change on first login^)
echo   Master reset: NTZHSS
echo.
echo Start the app with:  Run_WebCrawlerEnterprise.bat
echo.
pause
