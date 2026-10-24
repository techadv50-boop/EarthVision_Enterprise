# Checks the one-employee pilot without changing the PC.
$ErrorActionPreference = "Continue"
$failed = 0
function Report-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) {
        Write-Host "PASS  $Name  $Detail"
    }
    else {
        Write-Host "FAIL  $Name  $Detail"
        $script:failed++
    }
}

$root = "C:\ProgramData\WorkPilot"
$configPath = Join-Path $root "pilot.json"
Report-Check "Config file" (Test-Path $configPath) $configPath
if (-not (Test-Path $configPath)) { exit 1 }
$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$userName = [string]$config.userName

$user = Get-LocalUser -Name $userName -ErrorAction SilentlyContinue
Report-Check "Employee login" ($null -ne $user) $userName
$admins = @(Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "\\$([regex]::Escape($userName))$" })
Report-Check "Login is not an administrator" ($admins.Count -eq 0) $userName
$remote = @(Get-LocalGroupMember -Group "Remote Desktop Users" -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "\\$([regex]::Escape($userName))$" })
Report-Check "Remote Desktop allowed" ($remote.Count -eq 1) $userName

$chromeKey = "HKLM:\SOFTWARE\Policies\Google\Chrome"
$history = $null
$incognito = $null
$guest = $null
if (Test-Path $chromeKey) {
    $values = Get-ItemProperty $chromeKey
    $history = $values.AllowDeletingBrowserHistory
    $incognito = $values.IncognitoModeAvailability
    $guest = $values.BrowserGuestModeEnabled
}
Report-Check "Chrome history cannot be cleared" ($history -eq 0) "AllowDeletingBrowserHistory=$history"
Report-Check "Chrome Incognito is off" ($incognito -eq 1) "IncognitoModeAvailability=$incognito"
Report-Check "Chrome Guest mode is off" ($guest -eq 0) "BrowserGuestModeEnabled=$guest"

$work = [string]$config.workFolder
Report-Check "Work folder" (Test-Path $work) $work
Report-Check "Report folder" (Test-Path (Join-Path $root "Reports")) (Join-Path $root "Reports")
$tracker = Get-ScheduledTask -TaskName "WorkPilot Session Tracker" -ErrorAction SilentlyContinue
$report = Get-ScheduledTask -TaskName "WorkPilot Session Report" -ErrorAction SilentlyContinue
Report-Check "Sign-in recorder" ($null -ne $tracker) "WorkPilot Session Tracker"
Report-Check "Report task" ($null -ne $report) "WorkPilot Session Report"

if ($failed -gt 0) {
    Write-Host "$failed check(s) failed."
    exit 1
}
Write-Host "Pilot checks passed."
exit 0
