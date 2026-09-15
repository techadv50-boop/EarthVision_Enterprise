# Register optional automatic backups with Windows Task Scheduler.
# Default application behaviour is OFF. Run this only after a successful manual backup.
# Usage: .\register-scheduled-backup.ps1 -ExePath "C:\Program Files\ServerBackup\ServerBackup.exe"

param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [string]$ConfigPath = "$env:APPDATA\ServerBackup\config.json",
    [ValidateSet("DAILY", "WEEKLY")]
    [string]$Schedule = "DAILY",
    [string]$Time = "02:00",
    [string]$TaskName = "ServerBackup-Ubuntu"
)

if (-not (Test-Path $ExePath)) {
    Write-Error "Executable not found: $ExePath"
    exit 1
}

$command = "`"$ExePath`" --backup --mode scheduled --config `"$ConfigPath`""
schtasks /Create /F /TN $TaskName /TR $command /SC $Schedule /ST $Time /RL LIMITED
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create scheduled task."
    exit $LASTEXITCODE
}
Write-Host "Scheduled task $TaskName created. It uses the same engine as BACKUP NOW."
