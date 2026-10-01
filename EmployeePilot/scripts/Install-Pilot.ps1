# One-employee pilot on this Windows 11 Pro PC.
# Creates a standard login, a disk limit, Chrome rules, recording, and a sign-out report.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$UserName = "employee1",
    [string]$FullName = "Pilot Employee",
    [securestring]$Password,
    [int]$QuotaGB = 80,
    [int]$IdleMinutes = 5,
    [string]$Volume,
    [switch]$SkipRemoteDesktop,
    [switch]$SkipQuota,
    [switch]$SkipChromePolicy,
    [switch]$SkipAppLocker
)

$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Open PowerShell as Administrator, then run Install-Pilot.ps1 again."
}

$source = Split-Path -Parent $PSScriptRoot
$modulePath = Join-Path $source "src\WorkPilot.Report.psm1"
Import-Module $modulePath -Force

function ConvertFrom-SecureStringPlain {
    param([securestring]$Value)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

if (-not $PSBoundParameters.ContainsKey("UserName")) {
    $typed = Read-Host "Windows login for the employee (press Enter for employee1)"
    if ($typed) { $UserName = $typed.Trim() }
}
if (-not $PSBoundParameters.ContainsKey("FullName")) {
    $typed = Read-Host "Employee full name (press Enter for Pilot Employee)"
    if ($typed) { $FullName = $typed.Trim() }
}
if (-not $PSBoundParameters.ContainsKey("QuotaGB")) {
    $typed = Read-Host "Disk space for this employee in GB (press Enter for 80)"
    if ($typed) { $QuotaGB = [int]$typed }
}
if (-not $PSBoundParameters.ContainsKey("IdleMinutes")) {
    $typed = Read-Host "Minutes without mouse or keyboard before idle (press Enter for 5)"
    if ($typed) { $IdleMinutes = [int]$typed }
}
if ($IdleMinutes -lt 1 -or $IdleMinutes -gt 60) {
    throw "Idle minutes must be from 1 to 60."
}
if ($QuotaGB -lt 20) {
    throw "Use at least 20 GB so the Windows profile and Chrome still fit."
}
if (-not $Password -and -not $WhatIfPreference) {
    $Password = Read-Host -AsSecureString -Prompt "Password for $UserName"
    $confirm = Read-Host -AsSecureString -Prompt "Type the same password again"
    $first = ConvertFrom-SecureStringPlain $Password
    $second = ConvertFrom-SecureStringPlain $confirm
    if ($first -ne $second) {
        throw "The passwords did not match. Run the installer again."
    }
    $first = $null
    $second = $null
}

function Select-PilotVolume {
    if ($Volume) {
        $letter = $Volume.Trim().TrimEnd("\")
        if ($letter -notmatch "^[A-Za-z]:$") { throw "Volume must look like C: or D:" }
        return $letter.ToUpper()
    }
    $disks = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3"
    $data = $disks | Where-Object { $_.DeviceID -ne "C:" -and $_.FileSystem -eq "NTFS" } | Sort-Object FreeSpace -Descending | Select-Object -First 1
    if ($data) { return $data.DeviceID }
    return "C:"
}

$volumeLetter = Select-PilotVolume
$root = "C:\ProgramData\WorkPilot"
$workFolder = Join-Path "$volumeLetter\" (Join-Path "WorkPilot" $UserName)
$template = Get-Content -Path (Join-Path $source "config\pilot.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$template.employeeName = $FullName
$template.userName = $UserName
$template.idleThresholdSeconds = $IdleMinutes * 60
$template.pollSeconds = 5
$template.quotaGB = $QuotaGB
$template | Add-Member -NotePropertyName volume -NotePropertyValue $volumeLetter -Force
$template | Add-Member -NotePropertyName workFolder -NotePropertyValue $workFolder -Force

Write-Host ""
Write-Host "Pilot setup"
Write-Host "  Login:        $UserName"
Write-Host "  Name:         $FullName"
Write-Host "  Work folder:  $workFolder"
Write-Host "  Disk limit:   $QuotaGB GB on $volumeLetter"
Write-Host "  Idle after:   $IdleMinutes minutes"
Write-Host ""

if ($volumeLetter -eq "C:") {
    Write-Host "This PC will limit $UserName on drive C:. The limit includes their Windows profile and Chrome, not only documents."
}

function New-AccessRule {
    param([string]$Identity, [System.Security.AccessControl.FileSystemRights]$Rights)
    $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $none = [System.Security.AccessControl.PropagationFlags]::None
    New-Object System.Security.AccessControl.FileSystemAccessRule(
        $Identity, $Rights, $inherit, $none, "Allow"
    )
}

function Set-ProtectedAcl {
    param([string]$Path, [System.Security.AccessControl.FileSystemAccessRule[]]$Rules)
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in $Rules) { $acl.AddAccessRule($rule) }
    Set-Acl -Path $Path -AclObject $acl
}

if ($PSCmdlet.ShouldProcess($UserName, "Create the employee login and pilot folders")) {
    $existing = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
    if (-not $existing) {
        if (-not $Password) { throw "A password is required to create $UserName." }
        New-LocalUser -Name $UserName -FullName $FullName -Password $Password -Description "WorkPilot pilot employee" | Out-Null
        Write-Host "Created login $UserName."
    }
    else {
        Write-Host "Login $UserName already exists. The password was left unchanged."
        if ($FullName) {
            Set-LocalUser -Name $UserName -FullName $FullName
        }
    }
    $adminMembers = Get-LocalGroupMember -Group "Administrators" -ErrorAction SilentlyContinue
    if ($adminMembers | Where-Object { $_.Name -match "\\$([regex]::Escape($UserName))$" }) {
        Remove-LocalGroupMember -Group "Administrators" -Member $UserName
        Write-Host "Removed $UserName from Administrators."
    }
    $users = Get-LocalGroupMember -Group "Users" -ErrorAction SilentlyContinue
    if (-not ($users | Where-Object { $_.Name -match "\\$([regex]::Escape($UserName))$" })) {
        Add-LocalGroupMember -Group "Users" -Member $UserName
    }
    $remote = Get-LocalGroupMember -Group "Remote Desktop Users" -ErrorAction SilentlyContinue
    if (-not ($remote | Where-Object { $_.Name -match "\\$([regex]::Escape($UserName))$" })) {
        Add-LocalGroupMember -Group "Remote Desktop Users" -Member $UserName
    }

    New-Item -ItemType Directory -Path $root -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "journal") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "Reports") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "logs") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "src") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "scripts") -Force | Out-Null
    New-Item -ItemType Directory -Path $workFolder -Force | Out-Null

    $adminRule = New-AccessRule "BUILTIN\Administrators" "FullControl"
    $systemRule = New-AccessRule "NT AUTHORITY\SYSTEM" "FullControl"
    $userModify = New-AccessRule $UserName "Modify"
    $journalRights = [System.Security.AccessControl.FileSystemRights]::CreateFiles `
        -bor [System.Security.AccessControl.FileSystemRights]::AppendData `
        -bor [System.Security.AccessControl.FileSystemRights]::ReadAndExecute `
        -bor [System.Security.AccessControl.FileSystemRights]::ListDirectory `
        -bor [System.Security.AccessControl.FileSystemRights]::ReadAttributes `
        -bor [System.Security.AccessControl.FileSystemRights]::WriteAttributes
    $userJournal = New-AccessRule $UserName $journalRights
    Set-ProtectedAcl -Path $workFolder -Rules @($adminRule, $systemRule, $userModify)
    Set-ProtectedAcl -Path (Join-Path $root "journal") -Rules @($adminRule, $systemRule, $userJournal)
    Set-ProtectedAcl -Path (Join-Path $root "logs") -Rules @($adminRule, $systemRule, $userJournal)
    Set-ProtectedAcl -Path (Join-Path $root "Reports") -Rules @($adminRule, $systemRule)

    Copy-Item -Path (Join-Path $source "src\*") -Destination (Join-Path $root "src") -Force
    Copy-Item -Path (Join-Path $source "scripts\*") -Destination (Join-Path $root "scripts") -Force
    Copy-Item -Path (Join-Path $source "NOTICE.txt") -Destination (Join-Path $root "NOTICE.txt") -Force
    $notice = @"
Save your work in this folder.
Your space limit on drive $volumeLetter is $QuotaGB GB.
Recording is on while you are signed in. See the notice from your administrator.
"@
    Set-Content -Path (Join-Path $workFolder "READ-ME.txt") -Value $notice -Encoding UTF8
    $template | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $root "pilot.json") -Encoding UTF8

    if (-not $SkipQuota) {
        $quota = Get-WorkPilotQuotaBytes -QuotaGB $QuotaGB
        $account = "$env:COMPUTERNAME\$UserName"
        & fsutil.exe quota track $volumeLetter | Out-Null
        & fsutil.exe quota modify $volumeLetter $quota.SoftBytes $quota.HardBytes $account
        if ($LASTEXITCODE -ne 0) {
            throw "Disk quota could not be set for $account on $volumeLetter."
        }
        & fsutil.exe quota enforce $volumeLetter | Out-Null
        Write-Host "Disk limit is on: $QuotaGB GB for $account on $volumeLetter."
    }

    if (-not $SkipChromePolicy) {
        $chromeKey = "HKLM:\SOFTWARE\Policies\Google\Chrome"
        New-Item -Path $chromeKey -Force | Out-Null
        $policies = Get-WorkPilotChromePolicies
        foreach ($item in $policies.PSObject.Properties) {
            New-ItemProperty -Path $chromeKey -Name $item.Name -Value ([int]$item.Value) -PropertyType DWord -Force | Out-Null
        }
        Write-Host "Chrome policy: history cannot be cleared, Incognito is off, Guest mode is off."
    }

    if (-not $SkipRemoteDesktop) {
        Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name "fDenyTSConnections" -Value 0
        Enable-NetFirewallRule -DisplayGroup "Remote Desktop" | Out-Null
        Write-Host "Remote Desktop is on for $UserName."
    }

    $trackerAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\Start-SessionTracker.ps1`""
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $UserName
    $trackerPrincipal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Limited
    $trackerSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 7)
    Register-ScheduledTask -TaskName "WorkPilot Session Tracker" -Action $trackerAction -Trigger $logon -Principal $trackerPrincipal -Settings $trackerSettings -Force | Out-Null

    $reportAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\Update-SessionReport.ps1`""
    $reportStart = (Get-Date).AddMinutes(1)
    $reportTrigger = New-ScheduledTaskTrigger -Once -At $reportStart -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
    $reportPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $reportSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName "WorkPilot Session Report" -Action $reportAction -Trigger $reportTrigger -Principal $reportPrincipal -Settings $reportSettings -Force | Out-Null

    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $desktop "Work session report.lnk"))
    $shortcut.TargetPath = Join-Path $root "Reports\latest.html"
    $shortcut.Description = "Latest employee work session report"
    $shortcut.Save()
}

if (-not $SkipAppLocker -and -not $WhatIfPreference) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\Set-AllowedPrograms.ps1") -Mode Audit
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Program rules were not applied. The login, disk limit, Chrome rules, and recorder are still in place."
    }
}

Write-Host ""
Write-Host "Pilot is ready for one employee."
Write-Host "1. Update Windows if this PC is still on an old Windows 11 build, then restart."
Write-Host "2. Sign in once as $UserName at this computer and confirm you see the recording message."
Write-Host "3. Open Chrome and confirm history cannot be cleared."
Write-Host "4. Sign out. Wait one minute. Open the Work session report shortcut on your administrator desktop."
Write-Host "5. Give the employee NOTICE.txt and the login only after that test looks right."
Write-Host "Reports stay in $root\Reports"
Write-Host "Do not open Remote Desktop directly to the internet. Use a private network such as Tailscale, then connect to this PC."
Write-Host "Program blocking is in audit mode. Nothing is blocked yet. After a real work day, review the report, then run:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$root\scripts\Set-AllowedPrograms.ps1`" -Mode Enforce"
