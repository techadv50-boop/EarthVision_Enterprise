# Report math for the one-employee pilot. Runs on Windows PowerShell 5.1 and PowerShell 7.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root "src\WorkPilot.Report.psm1") -Force

$failed = 0
function Assert-Equal {
    param([string]$Name, $Actual, $Expected)
    if ($Actual -ne $Expected) {
        Write-Host "FAIL $Name"
        Write-Host "  actual:   $Actual"
        Write-Host "  expected: $Expected"
        $script:failed++
    }
    else {
        Write-Host "PASS $Name"
    }
}

function At {
    param([string]$Iso, [int]$IdleSeconds, [string]$Process, [string]$Title, [bool]$Locked = $false)
    [pscustomobject]@{
        Utc         = $Iso
        IdleSeconds = $IdleSeconds
        Process     = $Process
        Title       = $Title
        Locked      = $Locked
    }
}

$policies = Get-WorkPilotChromePolicies
Assert-Equal "history deletion blocked" $policies.AllowDeletingBrowserHistory 0
Assert-Equal "incognito disabled" $policies.IncognitoModeAvailability 1
Assert-Equal "guest mode disabled" $policies.BrowserGuestModeEnabled 0

$quota = Get-WorkPilotQuotaBytes -QuotaGB 80
Assert-Equal "hard quota bytes" $quota.HardBytes ([uint64]80 * 1GB)
Assert-Equal "soft quota bytes" $quota.SoftBytes ([uint64]([math]::Floor((80GB) * 0.9)))

$empty = Get-WorkPilotSummary -Samples @() -IdleThresholdSeconds 300
Assert-Equal "empty session seconds" $empty.SessionSeconds 0
Assert-Equal "empty active" $empty.ActiveSeconds 0

# 40 minutes of continuous input in Chrome. Threshold 5 minutes.
$continuous = @()
for ($minute = 0; $minute -le 40; $minute++) {
    $stamp = "2026-09-30T09:{0:00}:00Z" -f $minute
    $continuous += At $stamp 0 "chrome.exe" "Inbox"
}
$continuousSummary = Get-WorkPilotSummary -Samples $continuous -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe")
Assert-Equal "continuous session" $continuousSummary.SessionSeconds (40 * 60)
Assert-Equal "continuous active" $continuousSummary.ActiveSeconds (40 * 60)
Assert-Equal "continuous idle" $continuousSummary.IdleSeconds 0
Assert-Equal "continuous chrome" @($continuousSummary.Programs)[0].ActiveSeconds (40 * 60)
Assert-Equal "continuous allowed" @($continuousSummary.Programs)[0].Group "Allowed"
Assert-Equal "continuous timeline rows" @($continuousSummary.Timeline).Count 1
Assert-Equal "continuous outside count" @($continuousSummary.OutsidePrograms).Count 0

# Typed until 09:10, next input at 09:25, then until 09:40. Threshold 5 minutes.
# Active 09:00-09:15 and 09:25-09:40. Idle 09:15-09:25.
$split = @()
for ($minute = 0; $minute -le 40; $minute++) {
    $stamp = "2026-09-30T09:{0:00}:00Z" -f $minute
    $idle = 0
    $process = "chrome.exe"
    $title = "Inbox"
    if ($minute -gt 10 -and $minute -lt 25) {
        $idle = ($minute - 10) * 60
    }
    if ($minute -ge 25) {
        $process = "WINWORD.EXE"
        $title = "Report.docx"
    }
    $split += At $stamp $idle $process $title
}
$splitSummary = Get-WorkPilotSummary -Samples $split -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe", "WINWORD.EXE")
Assert-Equal "split session" $splitSummary.SessionSeconds (40 * 60)
Assert-Equal "split active" $splitSummary.ActiveSeconds (30 * 60)
Assert-Equal "split idle" $splitSummary.IdleSeconds (10 * 60)
Assert-Equal "split longest" $splitSummary.LongestIdleSeconds (10 * 60)
Assert-Equal "split percent" $splitSummary.ActivePercent 75

# A 4 minute gap stays active when the threshold is 5 minutes.
$shortGap = @(
    (At "2026-09-30T10:00:00Z" 0 "EXCEL.EXE" "Sheet"),
    (At "2026-09-30T10:04:00Z" 0 "EXCEL.EXE" "Sheet")
)
$shortSummary = Get-WorkPilotSummary -Samples $shortGap -IdleThresholdSeconds 300 -AllowedPrograms @("EXCEL.EXE")
Assert-Equal "short gap active" $shortSummary.ActiveSeconds (4 * 60)
Assert-Equal "short gap idle" $shortSummary.IdleSeconds 0

# Exactly 5 minutes after the last input, the rest of the session is idle.
$exact = @(
    (At "2026-09-30T11:00:00Z" 0 "chrome.exe" "Search"),
    (At "2026-09-30T11:10:00Z" 600 "chrome.exe" "Search")
)
$exactSummary = Get-WorkPilotSummary -Samples $exact -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe")
Assert-Equal "exact active" $exactSummary.ActiveSeconds 300
Assert-Equal "exact idle" $exactSummary.IdleSeconds 300

# A program that is not on the list is reported as outside the allocation.
$outside = @()
for ($minute = 0; $minute -le 10; $minute++) {
    $outside += At ("2026-09-30T12:{0:00}:00Z" -f $minute) 0 "game.exe" "Level 1"
}
$outsideSummary = Get-WorkPilotSummary -Samples $outside -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe") -SystemPrograms @("explorer.exe")
Assert-Equal "outside group" @($outsideSummary.Programs)[0].Group "Outside"
Assert-Equal "outside seconds" @($outsideSummary.OutsidePrograms)[0].ActiveSeconds (10 * 60)

# Windows shell time is not an allocation violation.
$shell = @(
    (At "2026-09-30T13:00:00Z" 0 "explorer.exe" "File Explorer"),
    (At "2026-09-30T13:03:00Z" 0 "explorer.exe" "File Explorer")
)
$shellSummary = Get-WorkPilotSummary -Samples $shell -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe") -SystemPrograms @("explorer.exe")
Assert-Equal "shell group" @($shellSummary.Programs)[0].Group "Windows"
Assert-Equal "shell outside count" @($shellSummary.OutsidePrograms).Count 0

# A locked screen is idle immediately, even if the last input was recent.
$locked = @(
    (At "2026-09-30T14:00:00Z" 0 "chrome.exe" "Mail" $false),
    (At "2026-09-30T14:02:00Z" 0 "LockApp.exe" "Windows Default Lock Screen" $true),
    (At "2026-09-30T14:12:00Z" 600 "LockApp.exe" "Windows Default Lock Screen" $true)
)
$lockedSummary = Get-WorkPilotSummary -Samples $locked -IdleThresholdSeconds 300 -AllowedPrograms @("chrome.exe") -SystemPrograms @("LockApp.exe")
Assert-Equal "locked active" $lockedSummary.ActiveSeconds (2 * 60)
Assert-Equal "locked idle" $lockedSummary.IdleSeconds (10 * 60)
Assert-Equal "locked portion" $lockedSummary.LockedSeconds (10 * 60)

# Samples that arrive out of order still follow the clock.
$ordered = Get-WorkPilotSummary -Samples @(
    (At "2026-09-30T15:05:00Z" 0 "notepad.exe" "Notes"),
    (At "2026-09-30T15:00:00Z" 0 "notepad.exe" "Notes")
) -IdleThresholdSeconds 300 -AllowedPrograms @("notepad.exe")
Assert-Equal "reordered active" $ordered.ActiveSeconds (5 * 60)

$html = New-WorkPilotReportHtml -Summary $splitSummary -EmployeeName "Pilot <Employee>" -UserName "employee1" -ComputerName "DESKTOP-ENCM4H4"
if ($html -notmatch "Pilot &lt;Employee&gt;") {
    Write-Host "FAIL html escapes the employee name"
    $failed++
}
else { Write-Host "PASS html escapes the employee name" }
if ($html -notmatch "30 min") {
    Write-Host "FAIL html shows active time"
    $failed++
}
else { Write-Host "PASS html shows active time" }
if ($html -match "<script>") {
    Write-Host "FAIL html contains a script tag"
    $failed++
}
else { Write-Host "PASS html has no script tag" }

$text = New-WorkPilotReportText -Summary $splitSummary -EmployeeName "Pilot Employee" -UserName "employee1" -ComputerName "DESKTOP-ENCM4H4"
if ($text -notmatch "Longest idle stretch: 10 min") {
    Write-Host "FAIL text report longest idle"
    $failed++
}
else { Write-Host "PASS text report longest idle" }

if ($failed -gt 0) {
    Write-Host "$failed test(s) failed"
    exit 1
}
Write-Host "All report tests passed"
exit 0
