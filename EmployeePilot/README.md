# One-employee pilot for Windows 11 Pro

This pilot is for the Dell Precision 5820 (`DESKTOP-ENCM4H4`) as it is today: Windows 11 Pro, one employee signed in at a time. It does not install Windows Server and it does not use Ubuntu.

What the employee gets:

- A normal Windows login that is not an administrator
- A work folder with a disk limit (80 GB unless you choose another size)
- Chrome where they can browse and search, but cannot clear history, open Incognito, or use Guest mode
- A recorder that starts when they sign in and writes a report for you about every minute, including when they sign out

An example of the finished report is in `examples/sample-session-report.html`. On your PC the real report is `latest.html`.

What the report contains:

- Sign-in and sign-out time
- Active time and idle time
- The longest idle stretch
- Time spent in each program
- Programs that are not on your allowed list
- The window title that was in front of them

What it does not record: keystrokes, screenshots, passwords, clipboard, webcam, or microphone.

Idle means no mouse and no keyboard. The default wait is 5 minutes. Those 5 minutes still count as active, so reading a document is not idle. After 5 minutes the time is idle. Locking the screen is idle immediately.

## Before you install

1. On the Precision, open Settings, Windows Update, and install updates. The copy of Windows on this PC started as build 22000, which is the original Windows 11 release and no longer receives security updates. Stay on Windows 11 Pro. This is an update, not a new installation.
2. Install Google Chrome if it is not already installed.
3. Copy this `EmployeePilot` folder to the PC, for example to `C:\WorkPilotSetup`.

## Install

1. In that folder, double-click `Install.cmd`.
2. Approve the administrator prompt.
3. Press Enter to accept the defaults, or type your own values:
   - Login: `employee1`
   - Full name
   - Disk limit: `80` GB
   - Idle time: `5` minutes
   - A password you will give the employee
4. When it finishes, restart Windows if an update was waiting.

The installer also turns on Remote Desktop for this one login. Do not forward port 3389 on your router. From home, the employee should reach this PC through a private network (Tailscale is a simple option), then open Remote Desktop and sign in as `employee1`.

## Test it yourself before the employee uses it

1. Sign in as `employee1` at the tower.
2. A message says recording is on.
3. Open Chrome, visit a page, and try to clear browsing history. Chrome should refuse.
4. Leave the mouse and keyboard alone for 6 minutes.
5. Sign out. Wait one minute.
6. Sign back in as administrator.
7. Open **Work session report** on the administrator desktop, or open `C:\ProgramData\WorkPilot\Reports\latest.html`.

You should see Chrome in the program list, and about one minute of idle time after the 5-minute wait. The employee notice you can hand over is `NOTICE.txt`.

Check the setup at any time from an administrator PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ProgramData\WorkPilot\scripts\Verify-Pilot.ps1
```

## Allowed programs

The report marks these as allowed work programs: Chrome, Edge, Word, Excel, PowerPoint, Notepad, and Adobe Acrobat. Edit the list in `C:\ProgramData\WorkPilot\pilot.json` if the real work uses different programs. Windows itself (File Explorer, the Start menu, the lock screen) is listed separately and is not treated as a violation.

Blocking is off on the first day. AppLocker is in audit mode, so every program still runs, and administrators can always run everything. After one real work day, if the report only shows the programs you expect, turn blocking on:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ProgramData\WorkPilot\scripts\Set-AllowedPrograms.ps1 -Mode Enforce
```

That blocks downloaded programs and anything installed outside the allowed folders. Programs that already live in the Windows folder, including Notepad and PowerShell, still run. Sign in as `employee1` and open Chrome immediately after you turn this on. If Chrome does not open, switch back:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ProgramData\WorkPilot\scripts\Set-AllowedPrograms.ps1 -Mode Audit
```

## Where the files are

| Item | Place |
| --- | --- |
| Employee work files | `C:\WorkPilot\employee1` or `D:\WorkPilot\employee1` if this PC has a second NTFS disk |
| Reports | `C:\ProgramData\WorkPilot\Reports\latest.html` |
| Employee notice | `C:\ProgramData\WorkPilot\NOTICE.txt` |
| Recorder | Starts at sign-in. If they close it, it starts again within a minute |

The disk limit applies to files that login owns on that drive. On a PC with only drive C:, the limit includes the Windows profile and Chrome, so keep it at 80 GB or more.

## Remove the pilot

Double-click `Uninstall.cmd`. This removes the recorder, the Chrome rules added here, and the program policy. The login and the work files stay.

To also delete the login, from an administrator PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ProgramData\WorkPilot\scripts\Uninstall-Pilot.ps1 -RemoveUser
```

## Later, if this pilot works

This tower has 16 GB of RAM and Windows 11 Pro allows one interactive session. A second employee can take turns on the same PC: run the installer again with a different login name. Five people at the same time needs another computer for each person, or a later move to Windows Server with Remote Desktop licenses and more memory (32 GB minimum, 64 GB is the comfortable size on this Precision). That step is separate from this pilot.
