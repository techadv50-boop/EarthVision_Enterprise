$ErrorActionPreference = 'Continue'
$log = Join-Path $env:Public 'Desktop\Word-fix-log.txt'
function Log([string]$Message) {
    $line = (Get-Date -Format 'HH:mm:ss') + '  ' + $Message
    Add-Content -Path $log -Value $line
    Write-Host $line
}
Set-Content -Path $log -Value "Word fix started $(Get-Date)"

try {
    $q = & quser.exe employee1 2>$null
    if ($LASTEXITCODE -eq 0 -and $q) {
        foreach ($row in @($q | Select-Object -Skip 1)) {
            $id = ([regex]::Matches([string]$row, '\d+') | Select-Object -First 1).Value
            if ($id) {
                Log "Signing out employee1 session $id"
                & logoff.exe $id | Out-Null
            }
        }
        Start-Sleep -Seconds 2
    }
}
catch {
    Log $_.Exception.Message
}

Log 'Removing the program blocker'
& sc.exe stop AppIDSvc | Out-Null
& reg.exe add 'HKLM\SYSTEM\CurrentControlSet\Services\AppIDSvc' /v Start /t REG_DWORD /d 4 /f | Out-Null
& reg.exe delete 'HKLM\SOFTWARE\Policies\Microsoft\Windows\SrpV2' /f | Out-Null
& reg.exe delete 'HKLM\SOFTWARE\Policies\Microsoft\Windows\Safer' /f | Out-Null

foreach ($folder in @(
    'C:\',
    'C:\Windows',
    'C:\Program Files',
    'C:\Program Files (x86)',
    'C:\ProgramData'
)) {
    if (Test-Path $folder) {
        Log "Clearing the employee block on $folder"
        & icacls.exe $folder /remove:d employee1 /C | Out-Null
    }
}

foreach ($folder in @(
    'C:\Program Files\Microsoft Office',
    'C:\Program Files (x86)\Microsoft Office',
    'C:\Program Files\Common Files\Microsoft Shared',
    'C:\Program Files (x86)\Common Files\Microsoft Shared',
    'C:\ProgramData\Microsoft\Office',
    'C:\ProgramData\Microsoft\OfficeSoftwareProtectionPlatform'
)) {
    if (Test-Path $folder) {
        Log "Opening $folder. Please wait."
        & icacls.exe $folder /remove:d employee1 /T /C | Out-Null
        & icacls.exe $folder /grant 'BUILTIN\Users:(OI)(CI)RX' 'employee1:(OI)(CI)RX' /C | Out-Null
    }
}

$profile = 'C:\Users\employee1'
if (Test-Path "$profile\NTUSER.DAT") {
    & reg.exe unload 'HKU\EmpFix' | Out-Null
    & reg.exe load 'HKU\EmpFix' "$profile\NTUSER.DAT" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        & reg.exe delete 'HKU\EmpFix\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\DisallowRun' /f | Out-Null
        & reg.exe delete 'HKU\EmpFix\Software\Policies\Microsoft\Windows\Safer' /f | Out-Null
        foreach ($pair in @(
            @('HKU\EmpFix\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer', 'DisallowRun'),
            @('HKU\EmpFix\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer', 'NoRun'),
            @('HKU\EmpFix\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer', 'NoDrives'),
            @('HKU\EmpFix\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer', 'NoViewOnDrive'),
            @('HKU\EmpFix\Software\Policies\Microsoft\Windows\Installer', 'DisableMSI')
        )) {
            & reg.exe delete $pair[0] /v $pair[1] /f | Out-Null
        }
        & reg.exe unload 'HKU\EmpFix' | Out-Null
        Log 'Employee limits removed'
    }
    else {
        Log 'employee1 is still signed in. Sign that account out, then run this file again.'
    }
}

Log 'Looking for Word'
$found = $null
foreach ($root in @('C:\Program Files', 'C:\Program Files (x86)')) {
    if (-not (Test-Path $root)) { continue }
    $hit = Get-ChildItem -Path $root -Filter WINWORD.EXE -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { $found = $hit.FullName; break }
}
if (-not $found) {
    Log 'WINWORD.EXE was not found. Install Office again if the Word icon is missing.'
}
else {
    Log "Word program: $found"
    $dir = Split-Path $found
    & icacls.exe $dir /remove:d employee1 /T /C | Out-Null
    & icacls.exe $dir /grant 'BUILTIN\Users:(OI)(CI)RX' 'employee1:(OI)(CI)RX' /C | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    foreach ($desk in @((Join-Path $env:Public 'Desktop'), (Join-Path $profile 'Desktop'))) {
        $parent = Split-Path $desk -Parent
        if (-not (Test-Path $parent)) { continue }
        New-Item -ItemType Directory -Force -Path $desk | Out-Null
        $shortcut = $shell.CreateShortcut((Join-Path $desk 'Word.lnk'))
        $shortcut.TargetPath = $found
        $shortcut.WorkingDirectory = $dir
        $shortcut.Description = 'Word'
        $shortcut.Save()
        Log "Shortcut: $(Join-Path $desk 'Word.lnk')"
    }
}
Log 'Finished. Restart the computer. Sign in as employee1. Open the Word icon on the desktop.'
Start-Process notepad.exe $log
