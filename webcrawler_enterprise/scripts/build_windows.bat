@echo off
REM Build WebCrawler Enterprise for Windows
cd /d %~dp0
python -m pip install -r requirements.txt pyinstaller
python -m playwright install chromium
pyinstaller --noconfirm webcrawler_enterprise.spec
echo.
echo Build complete: dist\WebCrawlerEnterprise\WebCrawlerEnterprise.exe
pause
