@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Run Setup.bat first.
  pause
  exit /b 1
)

python -c "import PySide6, playwright, bs4, httpx, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo Dependencies missing. Running Setup.bat...
  call "%~dp0Setup.bat"
)

echo Starting WebCrawler Enterprise...
python main.py
if errorlevel 1 (
  echo.
  echo App exited with an error.
  pause
)
