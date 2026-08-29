@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo Starting DOI -^> ReDIF Converter...
"%PY%" DOI_REDIF_Converter.py
if errorlevel 1 (
  echo.
  echo If Python packages are missing, run:
  echo   python -m venv .venv
  echo   .venv\Scripts\activate
  echo   pip install -r requirements.txt
  pause
)
