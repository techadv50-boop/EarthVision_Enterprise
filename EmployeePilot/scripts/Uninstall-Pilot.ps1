# Removes the pilot recorder, Chrome rules added by the pilot, and the program policy.
# The employee login and work files stay unless you pass -RemoveUser or -RemoveFiles.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$RemoveUser,
    [switch]$RemoveFiles
)

$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Open PowerShell as Administrator, then run Uninstall-Pilot.ps1 again."
}

$root = "C:\ProgramData\WorkPilot"
$configPath = Join-Path $root "pilot.json"
$userName = "employee1"
if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $userName = [string]$config.userName
}

if ($PSCmdlet.ShouldProcess("WorkPilot", "Remove scheduled tasks and pilot policies")) {
    Unregister-ScheduledTask -TaskName "WorkPilot Session Tracker" -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "WorkPilot Session Report" -Confirm:$false -ErrorAction SilentlyContinue

    $chromeKey = "HKLM:\SOFTWARE\Policies\Google\Chrome"
    if (Test-Path $chromeKey) {
        foreach ($name in @("AllowDeletingBrowserHistory", "IncognitoModeAvailability", "BrowserGuestModeEnabled")) {
            Remove-ItemProperty -Path $chromeKey -Name $name -ErrorAction SilentlyContinue
        }
    }

    $backup = Join-Path $root "applocker-backup.xml"
    if (Test-Path $backup) {
        Set-AppLockerPolicy -XmlPolicy $backup
        Write-Host "Restored the previous AppLocker policy."
    }

    if ($RemoveUser) {
        $user = Get-LocalUser -Name $userName -ErrorAction SilentlyContinue
        if ($user) {
            Remove-LocalUser -Name $userName
            Write-Host "Removed login $userName."
        }
    }
    if ($RemoveFiles -and (Test-Path $root)) {
        Remove-Item -Path $root -Recurse -Force
        Write-Host "Removed $root"
    }
}

Write-Host "Pilot recorder removed. Work files were kept."
if (-not $RemoveUser) { Write-Host "Login $userName is still on this PC." }
