# Runs in the employee session from sign-in until sign-out.
# Appends one sample every few seconds. A separate administrator task
# turns those samples into the report.
$ErrorActionPreference = "Stop"

$root = "C:\ProgramData\WorkPilot"
$configPath = Join-Path $root "pilot.json"
if (-not (Test-Path $configPath)) {
    $configPath = Join-Path (Split-Path -Parent $PSScriptRoot) "config\pilot.json"
    $root = Split-Path -Parent $PSScriptRoot
}
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$poll = [int]$config.pollSeconds
if ($poll -lt 2) { $poll = 5 }

$journal = Join-Path $root "journal"
if (-not (Test-Path $journal)) {
    New-Item -ItemType Directory -Path $journal -Force | Out-Null
}
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logPath = Join-Path $logDir "tracker.log"

function Write-TrackerLog {
    param([string]$Message)
    $line = "{0}  {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

if (-not ("WorkPilotNative" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class WorkPilotNative {
    [StructLayout(LayoutKind.Sequential)]
    struct LASTINPUTINFO {
        public uint cbSize;
        public uint dwTime;
    }
    [DllImport("user32.dll")]
    static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    public static uint GetIdleSeconds() {
        LASTINPUTINFO info = new LASTINPUTINFO();
        info.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
        GetLastInputInfo(ref info);
        unchecked {
            return ((uint)Environment.TickCount - info.dwTime) / 1000;
        }
    }

    public static string GetForegroundTitle() {
        IntPtr hwnd = GetForegroundWindow();
        if (hwnd == IntPtr.Zero) { return ""; }
        StringBuilder buffer = new StringBuilder(512);
        GetWindowText(hwnd, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    public static uint GetForegroundProcessId() {
        IntPtr hwnd = GetForegroundWindow();
        uint processId = 0;
        if (hwnd == IntPtr.Zero) { return 0; }
        GetWindowThreadProcessId(hwnd, out processId);
        return processId;
    }
}
"@
}

$mutex = New-Object System.Threading.Mutex($false, "Local\WorkPilotSessionTracker")
if (-not $mutex.WaitOne(0)) {
    Write-TrackerLog "Tracker is already running."
    exit 0
}

$sessionId = Get-Date -Format "yyyyMMdd-HHmmss"
$sessionFile = Join-Path $journal ("{0}-{1}.jsonl" -f $config.userName, $sessionId)
Write-TrackerLog "Session $sessionId started for $($config.userName)."

try {
    & msg.exe $env:USERNAME /TIME:25 "Work session recording is on. This computer records the programs you use and idle time until you sign out. It does not record keystrokes or screenshots." | Out-Null
}
catch {
    Write-TrackerLog "Sign-in notice could not be shown."
}

function Get-ForegroundSample {
    $idle = [int][WorkPilotNative]::GetIdleSeconds()
    $processId = [int][WorkPilotNative]::GetForegroundProcessId()
    $title = [WorkPilotNative]::GetForegroundTitle()
    $process = "unknown.exe"
    if ($processId -gt 0) {
        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            $process = $proc.ProcessName
            if ($process -notmatch "\.exe$") { $process = "$process.exe" }
        }
        catch {
            $process = "unknown.exe"
        }
    }
    $locked = $process -match "^(?i)(LockApp|LogonUI)\.exe$"
    $safeTitle = (($title -replace "[\r\n]", " ").Trim())
    if ($safeTitle.Length -gt 180) { $safeTitle = $safeTitle.Substring(0, 180) }
    $payload = [ordered]@{
        sessionId   = $sessionId
        utc         = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        idleSeconds = $idle
        process     = $process
        title       = $safeTitle
        locked      = [bool]$locked
    }
    ($payload | ConvertTo-Json -Compress)
}

try {
    while ($true) {
        try {
            $line = Get-ForegroundSample
            Add-Content -Path $sessionFile -Value $line -Encoding UTF8
        }
        catch {
            Write-TrackerLog $_.Exception.Message
        }
        Start-Sleep -Seconds $poll
    }
}
finally {
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
    Write-TrackerLog "Session $sessionId stopped."
}
