@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  WebCrawler Enterprise - Diagnose
echo ============================================
echo.
echo Folder: %CD%
echo.

ver
echo.

if not exist "%~dp0WebCrawlerEnterprise.exe" (
  echo ERROR: WebCrawlerEnterprise.exe is missing.
  echo Unzip the FULL package. Do not run from inside the .zip directly.
  goto end
)

if not exist "%~dp0_internal" (
  echo ERROR: _internal folder is missing.
  echo The package is incomplete. Re-download and unzip again.
  goto end
)

if exist "%~dp0ms-playwright" (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
  echo Playwright browsers: FOUND
) else (
  echo Playwright browsers: NOT FOUND ^(app can still crawl via HTTP^)
)

echo.
echo Starting console build to capture errors...
echo If a window flashes and closes, read crash_log.txt in this folder.
echo.

if exist "%~dp0WebCrawlerEnterprise_Console.exe" (
  "%~dp0WebCrawlerEnterprise_Console.exe"
) else (
  "%~dp0WebCrawlerEnterprise.exe"
)

echo.
echo Exit code: %ERRORLEVEL%
if exist "%~dp0crash_log.txt" (
  echo.
  echo ---- crash_log.txt ----
  type "%~dp0crash_log.txt"
)

:end
echo.
pause
