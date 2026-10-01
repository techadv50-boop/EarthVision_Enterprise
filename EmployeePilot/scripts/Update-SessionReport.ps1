# Reads the employee session journal and writes the administrator report.
# Run as SYSTEM so the employee cannot change the finished report.
$ErrorActionPreference = "Stop"

$root = "C:\ProgramData\WorkPilot"
if (-not (Test-Path (Join-Path $root "pilot.json"))) {
    $root = Split-Path -Parent $PSScriptRoot
}
$configPath = Join-Path $root "pilot.json"
$modulePath = Join-Path $root "src\WorkPilot.Report.psm1"
Import-Module $modulePath -Force
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

$journal = Join-Path $root "journal"
$reports = Join-Path $root "Reports"
if (-not (Test-Path $reports)) {
    New-Item -ItemType Directory -Path $reports -Force | Out-Null
}
if (-not (Test-Path $journal)) {
    exit 0
}

$allowed = @($config.allowedPrograms)
$system = @()
if ($config.PSObject.Properties.Match("systemPrograms").Count -gt 0) {
    $system = @($config.systemPrograms)
}
$cutoff = (Get-Date).AddDays(-2)
$files = @(Get-ChildItem -Path $journal -Filter "*.jsonl" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $cutoff } |
    Sort-Object LastWriteTime)
if ($files.Count -eq 0) { exit 0 }

$latestHtml = $null
foreach ($file in $files) {
    $samples = New-Object System.Collections.ArrayList
    foreach ($line in [IO.File]::ReadAllLines($file.FullName)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $row = $line | ConvertFrom-Json
        }
        catch { continue }
        [void]$samples.Add([pscustomobject]@{
            Utc         = [string]$row.utc
            IdleSeconds = [int]$row.idleSeconds
            Process     = [string]$row.process
            Title       = [string]$row.title
            Locked      = [bool]$row.locked
        })
    }
    $summary = Get-WorkPilotSummary -Samples $samples.ToArray() -IdleThresholdSeconds ([int]$config.idleThresholdSeconds) -AllowedPrograms $allowed -SystemPrograms $system
    $base = [IO.Path]::GetFileNameWithoutExtension($file.Name)
    $htmlPath = Join-Path $reports "$base.html"
    $textPath = Join-Path $reports "$base.txt"
    $html = New-WorkPilotReportHtml -Summary $summary -EmployeeName $config.employeeName -UserName $config.userName -ComputerName $env:COMPUTERNAME
    $text = New-WorkPilotReportText -Summary $summary -EmployeeName $config.employeeName -UserName $config.userName -ComputerName $env:COMPUTERNAME
    [IO.File]::WriteAllText($htmlPath, $html, (New-Object System.Text.UTF8Encoding $false))
    [IO.File]::WriteAllText($textPath, $text, (New-Object System.Text.UTF8Encoding $false))
    $latestHtml = $htmlPath
}

if ($latestHtml) {
    Copy-Item -Path $latestHtml -Destination (Join-Path $reports "latest.html") -Force
    Copy-Item -Path ([IO.Path]::ChangeExtension($latestHtml, ".txt")) -Destination (Join-Path $reports "latest.txt") -Force
}

# If the employee closed the recorder, start it again while they are signed in.
& schtasks.exe /Query /TN "WorkPilot Session Tracker" 1>$null 2>$null
if ($LASTEXITCODE -eq 0) {
    & schtasks.exe /Run /TN "WorkPilot Session Tracker" 1>$null 2>$null
}
