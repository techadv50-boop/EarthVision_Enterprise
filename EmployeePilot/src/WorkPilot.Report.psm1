# Builds the one-employee session report from activity samples.
# Samples record the foreground program and seconds since the last
# mouse or keyboard input. They do not record keystrokes, screenshots,
# or passwords.

Set-StrictMode -Version 2.0

function Get-WorkPilotChromePolicies {
    # DWORD values under HKLM\SOFTWARE\Policies\Google\Chrome.
    # 0 = policy disabled, except IncognitoModeAvailability where 1 = Incognito disabled.
    [pscustomobject]@{
        AllowDeletingBrowserHistory = 0
        IncognitoModeAvailability   = 1
        BrowserGuestModeEnabled     = 0
    }
}

function Get-WorkPilotQuotaBytes {
    param([Parameter(Mandatory)][int]$QuotaGB)
    if ($QuotaGB -lt 1) {
        throw "Quota must be at least 1 GB."
    }
    $hard = [uint64]$QuotaGB * 1GB
    $soft = [uint64][math]::Floor($hard * 0.9)
    [pscustomobject]@{
        SoftBytes = $soft
        HardBytes = $hard
    }
}

function ConvertTo-PilotUtc {
    param($Value)
    if ($Value -is [datetime]) {
        $utc = [datetime]$Value
    }
    elseif ($Value -is [datetimeoffset]) {
        return $Value.UtcDateTime
    }
    else {
        $utc = [datetime]::Parse(
            [string]$Value,
            [cultureinfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AdjustToUniversal
        )
    }
    if ($utc.Kind -eq [DateTimeKind]::Utc) {
        return $utc
    }
    if ($utc.Kind -eq [DateTimeKind]::Local) {
        return $utc.ToUniversalTime()
    }
    return [datetime]::SpecifyKind($utc, [DateTimeKind]::Utc)
}

function ConvertTo-PilotSample {
    param($Sample)
    $idle = 0
    if ($null -ne $Sample.IdleSeconds) {
        $idle = [int]$Sample.IdleSeconds
    }
    if ($idle -lt 0) { $idle = 0 }
    if ($idle -gt 604800) { $idle = 604800 }

    $utc = ConvertTo-PilotUtc $Sample.Utc
    $process = [IO.Path]::GetFileName([string]$Sample.Process)
    if ([string]::IsNullOrWhiteSpace($process)) {
        $process = "unknown.exe"
    }
    $title = [string]$Sample.Title
    if ($null -eq $title) { $title = "" }
    $title = ($title -replace "[\r\n\t]", " ").Trim()
    if ($title.Length -gt 180) {
        $title = $title.Substring(0, 180)
    }
    $locked = $false
    if ($Sample.PSObject.Properties.Match("Locked").Count -gt 0 -and $Sample.Locked) {
        $locked = $true
    }
    [pscustomobject]@{
        Utc        = $utc
        IdleSeconds = $idle
        LastInput  = $utc.AddSeconds(-1 * $idle)
        Process    = $process
        Title      = $title
        Locked     = $locked
    }
}

function Test-PilotNameInList {
    param([string]$Name, [string[]]$List)
    $base = [IO.Path]::GetFileName($Name)
    foreach ($item in $List) {
        if ([string]::Equals([IO.Path]::GetFileName([string]$item), $base, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Format-PilotDuration {
    param([int]$Seconds)
    if ($Seconds -lt 0) { $Seconds = 0 }
    $hours = [math]::Floor($Seconds / 3600)
    $minutes = [math]::Floor(($Seconds % 3600) / 60)
    $remain = $Seconds % 60
    if ($hours -gt 0 -and $minutes -eq 0) {
        return ("{0} h" -f $hours)
    }
    if ($hours -gt 0) {
        return ("{0} h {1} min" -f $hours, $minutes)
    }
    if ($minutes -gt 0 -and $remain -eq 0) {
        return ("{0} min" -f $minutes)
    }
    if ($minutes -gt 0) {
        return ("{0} min {1} s" -f $minutes, $remain)
    }
    return ("{0} s" -f $remain)
}

function Format-PilotClock {
    param([datetime]$Utc)
    $Utc.ToString("yyyy-MM-dd HH:mm:ss 'UTC'", [cultureinfo]::InvariantCulture)
}

function ConvertTo-HtmlText {
    param([string]$Text)
    if ($null -eq $Text) { return "" }
    return ($Text -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;' -replace '"', '&quot;')
}

function Get-WorkPilotSummary {
    param(
        [array]$Samples,
        [int]$IdleThresholdSeconds = 300,
        [string[]]$AllowedPrograms = @(),
        [string[]]$SystemPrograms = @()
    )
    if ($IdleThresholdSeconds -lt 1) {
        throw "Idle threshold must be at least 1 second."
    }
    $emptyPrograms = @()
    $summary = [pscustomobject]@{
        SessionStart          = $null
        SessionEnd            = $null
        SessionSeconds        = 0
        ActiveSeconds         = 0
        IdleSeconds           = 0
        LockedSeconds         = 0
        LongestIdleSeconds    = 0
        ActivePercent         = 0
        FirstActive           = $null
        LastActive            = $null
        Programs              = $emptyPrograms
        OutsidePrograms       = $emptyPrograms
        Timeline              = $emptyPrograms
        IdleThresholdSeconds  = $IdleThresholdSeconds
        SampleCount           = 0
    }
    if ($null -eq $Samples -or $Samples.Count -eq 0) {
        return $summary
    }

    $points = @($Samples | ForEach-Object { ConvertTo-PilotSample $_ } | Sort-Object Utc, Process)
    $summary.SampleCount = $points.Count
    $sessionStart = $points[0].Utc
    $sessionEnd = $points[$points.Count - 1].Utc
    $summary.SessionStart = $sessionStart
    $summary.SessionEnd = $sessionEnd
    if ($sessionEnd -le $sessionStart) {
        return $summary
    }

    $runningLast = $points[0].LastInput
    $normalized = New-Object System.Collections.ArrayList
    foreach ($point in $points) {
        if ($point.LastInput -gt $runningLast) {
            $runningLast = $point.LastInput
        }
        [void]$normalized.Add([pscustomobject]@{
            Utc               = $point.Utc
            LastInput         = $point.LastInput
            RunningLastInput  = $runningLast
            Process           = $point.Process
            Title             = $point.Title
            Locked            = $point.Locked
        })
    }

    $boundaryMap = @{}
    $boundaryMap[$sessionStart.Ticks] = $sessionStart
    $boundaryMap[$sessionEnd.Ticks] = $sessionEnd
    foreach ($point in $normalized) {
        $cut = $point.LastInput.AddSeconds($IdleThresholdSeconds)
        if ($cut -gt $sessionStart -and $cut -lt $sessionEnd) {
            $boundaryMap[$cut.Ticks] = $cut
        }
        if ($point.Utc -gt $sessionStart -and $point.Utc -lt $sessionEnd) {
            $boundaryMap[$point.Utc.Ticks] = $point.Utc
        }
    }
    $boundaries = @($boundaryMap.Values | Sort-Object)

    $raw = New-Object System.Collections.ArrayList
    $index = 0
    for ($i = 0; $i -lt ($boundaries.Count - 1); $i++) {
        $start = $boundaries[$i]
        $end = $boundaries[$i + 1]
        $seconds = [int][math]::Round(($end - $start).TotalSeconds)
        if ($seconds -le 0) { continue }
        while (($index + 1) -lt $normalized.Count -and $normalized[$index + 1].Utc -le $start) {
            $index++
        }
        $known = $normalized[$index]
        $awayKind = $null
        if ($known.Locked) {
            $awayKind = "Locked"
        }
        elseif ($start -ge $known.RunningLastInput.AddSeconds($IdleThresholdSeconds)) {
            $awayKind = "Idle"
        }
        if ($awayKind) {
            [void]$raw.Add([pscustomobject]@{
                Start    = $start
                End      = $end
                Seconds  = $seconds
                Kind     = $awayKind
                Process  = ""
                Title    = ""
            })
        }
        else {
            [void]$raw.Add([pscustomobject]@{
                Start    = $start
                End      = $end
                Seconds  = $seconds
                Kind     = "Active"
                Process  = $known.Process
                Title    = $known.Title
            })
        }
    }

    $merged = New-Object System.Collections.ArrayList
    foreach ($slice in $raw) {
        if ($merged.Count -eq 0) {
            [void]$merged.Add($slice)
            continue
        }
        $previous = $merged[$merged.Count - 1]
        $same = $previous.Kind -eq $slice.Kind -and $previous.Process -eq $slice.Process -and $previous.Title -eq $slice.Title
        if ($same) {
            $previous.End = $slice.End
            $previous.Seconds = [int]($previous.Seconds + $slice.Seconds)
        }
        else {
            [void]$merged.Add($slice)
        }
    }

    $active = 0
    $idle = 0
    $locked = 0
    $longest = 0
    $awayRun = 0
    $firstActive = $null
    $lastActive = $null
    $byProgram = @{}
    foreach ($slice in $merged) {
        if ($slice.Kind -eq "Active") {
            $active += $slice.Seconds
            $awayRun = 0
            if ($null -eq $firstActive) { $firstActive = $slice.Start }
            $lastActive = $slice.End
            $key = $slice.Process.ToLowerInvariant()
            if (-not $byProgram.ContainsKey($key)) {
                $isAllowed = Test-PilotNameInList $slice.Process $AllowedPrograms
                $isSystem = Test-PilotNameInList $slice.Process $SystemPrograms
                $group = "Outside"
                if ($isAllowed) { $group = "Allowed" }
                elseif ($isSystem) { $group = "Windows" }
                $byProgram[$key] = [pscustomobject]@{
                    Process       = $slice.Process
                    ActiveSeconds = 0
                    Group         = $group
                }
            }
            $byProgram[$key].ActiveSeconds += $slice.Seconds
        }
        else {
            $idle += $slice.Seconds
            if ($slice.Kind -eq "Locked") { $locked += $slice.Seconds }
            $awayRun += $slice.Seconds
            if ($awayRun -gt $longest) { $longest = $awayRun }
        }
    }

    $sessionSeconds = [int][math]::Round(($sessionEnd - $sessionStart).TotalSeconds)
    $programs = @($byProgram.Values | Sort-Object ActiveSeconds -Descending)
    $outside = @($programs | Where-Object { $_.Group -eq "Outside" })
    $percent = 0
    if ($sessionSeconds -gt 0) {
        $percent = [math]::Round(100.0 * $active / $sessionSeconds, 1)
    }

    $summary.SessionSeconds = $sessionSeconds
    $summary.ActiveSeconds = $active
    $summary.IdleSeconds = $idle
    $summary.LockedSeconds = $locked
    $summary.LongestIdleSeconds = $longest
    $summary.ActivePercent = $percent
    $summary.FirstActive = $firstActive
    $summary.LastActive = $lastActive
    $summary.Programs = $programs
    $summary.OutsidePrograms = $outside
    $summary.Timeline = @($merged)
    return $summary
}

function New-WorkPilotReportText {
    param(
        [Parameter(Mandatory)]$Summary,
        [string]$EmployeeName,
        [string]$UserName,
        [string]$ComputerName
    )
    $lines = New-Object System.Collections.ArrayList
    [void]$lines.Add("Work session report")
    [void]$lines.Add("Employee: $EmployeeName")
    [void]$lines.Add("Windows login: $UserName")
    [void]$lines.Add("Computer: $ComputerName")
    if ($Summary.SessionStart) {
        [void]$lines.Add("Session start: $(Format-PilotClock $Summary.SessionStart)")
        [void]$lines.Add("Session end: $(Format-PilotClock $Summary.SessionEnd)")
    }
    else {
        [void]$lines.Add("Session start: no activity recorded")
        [void]$lines.Add("Session end: no activity recorded")
    }
    [void]$lines.Add("Session length: $(Format-PilotDuration $Summary.SessionSeconds)")
    [void]$lines.Add("Active time: $(Format-PilotDuration $Summary.ActiveSeconds)")
    [void]$lines.Add("Idle time: $(Format-PilotDuration $Summary.IdleSeconds)")
    [void]$lines.Add("Locked screen (included in idle): $(Format-PilotDuration $Summary.LockedSeconds)")
    [void]$lines.Add("Longest idle stretch: $(Format-PilotDuration $Summary.LongestIdleSeconds)")
    [void]$lines.Add("Active percent: $($Summary.ActivePercent)")
    [void]$lines.Add("Idle rule: no mouse or keyboard for $([int]($Summary.IdleThresholdSeconds / 60)) min still counts the waiting period as active; after that the time is idle. A locked screen is idle immediately.")
    [void]$lines.Add("")
    [void]$lines.Add("Programs")
    if (@($Summary.Programs).Count -eq 0) {
        [void]$lines.Add("(none)")
    }
    foreach ($program in @($Summary.Programs)) {
        [void]$lines.Add("$($program.Process)  $(Format-PilotDuration $program.ActiveSeconds)  $($program.Group)")
    }
    [void]$lines.Add("")
    [void]$lines.Add("Outside the allowed list")
    if (@($Summary.OutsidePrograms).Count -eq 0) {
        [void]$lines.Add("(none)")
    }
    foreach ($program in @($Summary.OutsidePrograms)) {
        [void]$lines.Add("$($program.Process)  $(Format-PilotDuration $program.ActiveSeconds)")
    }
    [void]$lines.Add("")
    [void]$lines.Add("Timeline")
    foreach ($slice in @($Summary.Timeline)) {
        $label = $slice.Kind
        if ($slice.Kind -eq "Active") {
            $label = "$($slice.Process)  $($slice.Title)"
        }
        [void]$lines.Add("$(Format-PilotClock $slice.Start)  $(Format-PilotDuration $slice.Seconds)  $label")
    }
    return ($lines -join "`r`n")
}

function New-WorkPilotReportHtml {
    param(
        [Parameter(Mandatory)]$Summary,
        [string]$EmployeeName,
        [string]$UserName,
        [string]$ComputerName
    )
    $name = ConvertTo-HtmlText $EmployeeName
    $login = ConvertTo-HtmlText $UserName
    $computer = ConvertTo-HtmlText $ComputerName
    $start = "No activity recorded"
    $end = "No activity recorded"
    if ($Summary.SessionStart) {
        $start = ConvertTo-HtmlText (Format-PilotClock $Summary.SessionStart)
        $end = ConvertTo-HtmlText (Format-PilotClock $Summary.SessionEnd)
    }
    $programRows = ""
    foreach ($program in $Summary.Programs) {
        $programRows += "<tr><td>$(ConvertTo-HtmlText $program.Process)</td><td>$(Format-PilotDuration $program.ActiveSeconds)</td><td>$(ConvertTo-HtmlText $program.Group)</td></tr>`n"
    }
    if (-not $programRows) {
        $programRows = "<tr><td colspan=`"3`">No program time recorded</td></tr>`n"
    }
    $outsideRows = ""
    foreach ($program in $Summary.OutsidePrograms) {
        $outsideRows += "<tr><td>$(ConvertTo-HtmlText $program.Process)</td><td>$(Format-PilotDuration $program.ActiveSeconds)</td></tr>`n"
    }
    if (-not $outsideRows) {
        $outsideRows = "<tr><td colspan=`"2`">None</td></tr>`n"
    }
    $timeRows = ""
    foreach ($slice in $Summary.Timeline) {
        $what = $slice.Kind
        if ($slice.Kind -eq "Active") {
            $what = "$(ConvertTo-HtmlText $slice.Process) — $(ConvertTo-HtmlText $slice.Title)"
        }
        $timeRows += "<tr><td>$(ConvertTo-HtmlText (Format-PilotClock $slice.Start))</td><td>$(Format-PilotDuration $slice.Seconds)</td><td>$what</td></tr>`n"
    }
    if (-not $timeRows) {
        $timeRows = "<tr><td colspan=`"3`">No timeline</td></tr>`n"
    }
    $idleMinutes = [int]($Summary.IdleThresholdSeconds / 60)
    @"
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Work session report</title>
<style>
body { font-family: Segoe UI, sans-serif; margin: 2rem; color: #1c1c1c; }
h1 { font-size: 1.5rem; margin-bottom: 0.2rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
p.note { color: #444; max-width: 46rem; }
.cards { display: flex; flex-wrap: wrap; gap: 0.8rem; margin: 1rem 0; }
.card { border: 1px solid #ccc; padding: 0.8rem 1rem; min-width: 9rem; }
.card span { display: block; font-size: 0.8rem; color: #555; }
.card strong { font-size: 1.35rem; }
table { border-collapse: collapse; width: 100%; max-width: 56rem; }
th, td { border-bottom: 1px solid #ddd; text-align: left; padding: 0.35rem 0.5rem; vertical-align: top; }
th { background: #f4f4f4; }
tr.outside td { background: #fff6e8; }
</style>
</head>
<body>
<h1>Work session report</h1>
<p class="note">This report lists programs in the foreground, how long each one was used, and idle time. It does not include keystrokes, screenshots, passwords, or the clipboard.</p>
<p>Employee: <strong>$name</strong><br>
Windows login: <strong>$login</strong><br>
Computer: <strong>$computer</strong><br>
Session start: $start<br>
Session end: $end</p>
<div class="cards">
<div class="card"><span>Session length</span><strong>$(Format-PilotDuration $Summary.SessionSeconds)</strong></div>
<div class="card"><span>Active time</span><strong>$(Format-PilotDuration $Summary.ActiveSeconds)</strong></div>
<div class="card"><span>Idle time</span><strong>$(Format-PilotDuration $Summary.IdleSeconds)</strong></div>
<div class="card"><span>Longest idle stretch</span><strong>$(Format-PilotDuration $Summary.LongestIdleSeconds)</strong></div>
<div class="card"><span>Active percent</span><strong>$($Summary.ActivePercent)%</strong></div>
</div>
<p class="note">Idle rule used for this report: $idleMinutes minutes without mouse or keyboard. That waiting period still counts as active, so reading and short pauses are not idle. After $idleMinutes minutes the time is idle. A locked screen counts as idle immediately. Locked time inside this session: $(Format-PilotDuration $Summary.LockedSeconds).</p>
<h2>Programs</h2>
<table>
<thead><tr><th>Program</th><th>Active time</th><th>Allocation</th></tr></thead>
<tbody>
$programRows
</tbody>
</table>
<h2>Outside the allowed list</h2>
<table>
<thead><tr><th>Program</th><th>Active time</th></tr></thead>
<tbody>
$outsideRows
</tbody>
</table>
<h2>Timeline</h2>
<table>
<thead><tr><th>Start</th><th>Length</th><th>What was on screen</th></tr></thead>
<tbody>
$timeRows
</tbody>
</table>
</body>
</html>
"@
}

Export-ModuleMember -Function @(
    "Get-WorkPilotChromePolicies",
    "Get-WorkPilotQuotaBytes",
    "Get-WorkPilotSummary",
    "New-WorkPilotReportHtml",
    "New-WorkPilotReportText",
    "Format-PilotDuration",
    "ConvertTo-HtmlText"
)
