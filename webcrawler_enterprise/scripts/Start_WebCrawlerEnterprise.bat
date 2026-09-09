@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "%~dp0WebCrawlerEnterprise.exe" (
  echo WebCrawlerEnterprise.exe not found.
  echo Unzip the complete package first.
  pause
  exit /b 1
)

if not exist "%~dp0_internal" (
  echo ERROR: _internal folder missing. Package is incomplete.
  echo Download again and extract ALL files.
  pause
  exit /b 1
)

if exist "%~dp0ms-playwright" (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
)

start "" "%~dp0WebCrawlerEnterprise.exe"
