@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo  DOI/URL to ReDIF  -  STANDALONE v1.4.1
echo  Native desktop window  -  NO BROWSER
echo  Archive crawler uses sitemap for full coverage
echo ==============================================
echo.
echo IMPORTANT:
echo  - Delete any OLD DOI_REDIF folders first
echo  - If SmartScreen appears: More info -^> Run anyway
echo.

if exist "DOI_URL_REDIF_Standalone.exe" (
  start "" "DOI_URL_REDIF_Standalone.exe"
  echo Launched DOI_URL_REDIF_Standalone.exe
  echo Window title should include: Standalone v1.4.1
  echo.
  echo Use section 1 to crawl an archive URL for article links.
  echo Then click Start conversion.
  echo.
  pause
  exit /b 0
)

echo ERROR: DOI_URL_REDIF_Standalone.exe not found.
echo Unzip this release fully into its own folder, then run again.
echo.
pause
exit /b 1
