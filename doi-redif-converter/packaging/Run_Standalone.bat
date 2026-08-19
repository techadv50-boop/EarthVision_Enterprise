@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo  DOI/URL to ReDIF  -  STANDALONE v1.3.0
echo  Native desktop window  -  NO BROWSER
echo ==============================================
echo.
echo IMPORTANT:
echo  - Delete any OLD DOI_REDIF_Converter folders first
echo  - If SmartScreen appears: More info -^> Run anyway
echo.

if exist "DOI_URL_REDIF_Standalone.exe" (
  start "" "DOI_URL_REDIF_Standalone.exe"
  echo Launched DOI_URL_REDIF_Standalone.exe
  echo You should see a DESKTOP WINDOW titled:
  echo   DOI/URL -^> ReDIF Standalone v1.3.0
  echo.
  echo Paste DOIs and/or article URLs, then click Start conversion.
  echo.
  pause
  exit /b 0
)

echo ERROR: DOI_URL_REDIF_Standalone.exe not found.
echo Unzip this release fully into its own folder, then run again.
echo.
pause
exit /b 1
