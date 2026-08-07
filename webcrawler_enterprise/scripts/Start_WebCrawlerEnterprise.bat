@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "%~dp0WebCrawlerEnterprise.exe" (
  echo WebCrawlerEnterprise.exe not found in this folder.
  echo Please unzip the full package and try again.
  pause
  exit /b 1
)

if exist "%~dp0ms-playwright" (
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
)

start "" "%~dp0WebCrawlerEnterprise.exe"
