@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  DOI / URL -^> ReDIF Converter
echo  Standalone desktop app (no browser)
echo ============================================
echo.
echo Starting...
echo If Windows SmartScreen appears:
echo   click More info  -^>  Run anyway
echo.

if exist "DOI_REDIF_Converter.exe" (
  "DOI_REDIF_Converter.exe"
  if errorlevel 1 (
    echo.
    echo Program exited with an error.
    echo Check DOI_REDIF_Converter.log in this folder.
    pause
  )
  exit /b %errorlevel%
)

echo ERROR: DOI_REDIF_Converter.exe not found in this folder.
echo Unzip the download fully first, then run this file again.
echo.
pause
exit /b 1
