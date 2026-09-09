WebCrawler Enterprise — Standalone for Windows 10 / 11
======================================================

IMPORTANT
---------
- Supported: Windows 10 and Windows 11 (64-bit)
- NOT supported: Windows 7, Windows 8/8.1
  (Python/PySide6/Chromium no longer run on Windows 7)

No Python and no VS Code are required.

How to install / run
--------------------
1. Download WebCrawlerEnterprise-Standalone-Windows.zip
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

If it does not start on Windows 10
----------------------------------
1. Install Microsoft Visual C++ Redistributable (x64):
   https://aka.ms/vs/17/release/vc_redist.x64.exe
2. Reboot if asked
3. Run Diagnose.bat and open crash_log.txt if created
4. Windows SmartScreen: More info -> Run anyway
5. Keep _internal folder next to the .exe (do not move exe alone)

Windows 7 users
---------------
Use the separate package:
  WebCrawlerEnterprise-Standalone-Windows7
(built with Python 3.8 + Qt5 for Windows 7 SP1 64-bit and newer).
