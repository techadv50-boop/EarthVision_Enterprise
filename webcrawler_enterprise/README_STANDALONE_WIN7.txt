WebCrawler Enterprise — Standalone for Windows 7 SP1 / 8 / 10 / 11
==================================================================

IMPORTANT
---------
- This package is the Windows 7 compatible build (Python 3.8 + Qt5/PySide2)
- Supported: Windows 7 SP1 (64-bit) and newer
- Chromium/Playwright is NOT bundled on this build (HTTP crawl + PDF email scan still works)
- No Python and no VS Code are required

How to install / run
--------------------
1. Download WebCrawlerEnterprise-Standalone-Windows7.zip
2. Right-click zip -> Extract All... to a folder
   (Do NOT open/run from inside the zip)
3. Open the extracted folder
4. Double-click:  Start WebCrawler Enterprise.bat
   or WebCrawlerEnterprise.exe

Login
-----
Username: admin
Password: admin   (must change on first login)
Master reset: NTZHSS

If it does not start on Windows 7
---------------------------------
1. Install Microsoft Visual C++ Redistributable (x64):
   https://aka.ms/vs/16/release/vc_redist.x64.exe
2. Make sure Windows 7 SP1 is installed
3. Run Diagnose.bat and open crash_log.txt if created
4. Keep _internal folder next to the .exe (do not move exe alone)

Windows 10 / 11 users
---------------------
You may use this Win7 package, or the newer Win10/11 package
(WebCrawlerEnterprise-Standalone-Windows) which includes Playwright.
