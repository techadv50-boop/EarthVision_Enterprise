# Employee Monitoring Agent — Phase 1

Windows desktop agent for workstation **presence and availability** monitoring.

Phase 1 implements the agent itself. It runs in the system tray, starts with Windows, and is ready to send heartbeats to a future FastAPI server. It does **not** record keystrokes, passwords, mouse coordinates, screenshots, webcam, microphone, documents, clipboard, websites, or private messages.

## Phase 1 checklist

The automated tests in `tests/test_phase1_acceptance.py` cover:

1. Automatic start with Windows (HKCU Run key, `--background`)
2. Background / tray operation with no large window
3. Admin can see whether the agent is running (`--status` / `agent.status.json`)
4. Single instance via a named mutex (file lock on POSIX)
5. Password-protected dashboard
6. Password required every time the dashboard is opened
7. Closing the dashboard does not stop monitoring
8. Exit requires authentication and records `AGENT_EXIT`
9. Mouse/keyboard activity detected as last-input age only
10. 30 seconds idle → `INACTIVE`
11. Activity → `ACTIVE`
12. Windows lock → `LOCKED`
13. Windows unlock → `UNLOCKED`
14. Login / logout distinct from startup
15. Shutdown / restart recorded when Windows reports them
16. Agent start after restart
17. Automatic reconnect after startup
18. Unexpected offline uses last heartbeat; no invented shutdown time
19. Heartbeat client posts to `/api/v1/agent/heartbeat` for the FastAPI server

## Run from source (Windows)

```powershell
cd EmployeeAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

First run asks for Employee ID, Device ID, server URL, and a dashboard password. The password is stored as **PBKDF2-SHA256**, never as plain text.

After setup the agent stays in the system tray:

- Right-click: Open, Status, Settings, About, Exit
- **Open** / **Settings** / **Exit** require the password every time
- Closing the dashboard leaves monitoring running
- **Exit** stops monitoring only after authentication

Background start (used by Windows startup):

```powershell
python -m app.main --background
```

Is it running?

```powershell
python -m app.main --status
```

A second launch shows: `Employee Monitoring Agent is already running.`

## Tests

```powershell
cd EmployeeAgent
pip install pytest
pytest -v
```

Core tests do not need PySide6 and run on Linux CI.

## Package a Windows EXE

On Windows, with PySide6 installed:

```powershell
cd EmployeeAgent
pyinstaller employeeagent.spec
```

The EXE is registered at:

`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\EmployeeMonitoringAgent`

as `"EmployeeAgent.exe" --background`.

Startup registration failures are written to `%LOCALAPPDATA%\EmployeeMonitoringAgent\logs\agent.log`.

## Local data

`%LOCALAPPDATA%\EmployeeMonitoringAgent\`

| File | Purpose |
| --- | --- |
| `config.json` | Settings + password hash |
| `state.json` | Last status / heartbeat (unexpected-offline recovery) |
| `agent.status.json` | Live running snapshot for administrators |
| `audit.sqlite` | Event history |
| `logs\agent.log` | Agent log |

## Status model

| Condition | Status |
| --- | --- |
| Online + input | `ACTIVE` |
| Online + no input ≥ 30s | `INACTIVE` |
| Session locked | `LOCKED` |
| User logged out | `LOGGED_OUT` |
| Heartbeats lost | `OFFLINE` |
| New boot | `STARTUP` |
| Windows shutting down | `SHUTDOWN` |
| Crash / power loss then boot | `UNEXPECTED_OFFLINE` then `STARTUP` |

`INACTIVE` means the PC is reachable but idle. `OFFLINE` means the server can no longer communicate with the agent. They are not the same.

If the PC dies before a shutdown event is written, the agent does **not** invent a shutdown timestamp. The next startup records `UNEXPECTED_OFFLINE` at the last heartbeat (approximate start of the gap).

## FastAPI contract (later)

`POST {server_url}/api/v1/agent/heartbeat`

```json
{
  "protocol_version": 1,
  "employee_id": "12",
  "device_id": "EMP12-PC",
  "status": "ACTIVE",
  "activity_status": "ACTIVE",
  "connection_status": "CONNECTED",
  "timestamp": "2026-09-09T08:47:40Z",
  "last_input_age_seconds": 1.2,
  "boot_id": "boot-1777900000",
  "agent_version": "1.0.0"
}
```

Do not build the production web dashboard until this Phase 1 agent passes testing.
