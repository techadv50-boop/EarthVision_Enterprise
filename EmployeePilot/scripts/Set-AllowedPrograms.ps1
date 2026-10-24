# Builds an AppLocker executable policy for the pilot employee.
# Audit mode records what would be blocked and does not stop any program.
# Enforce mode blocks programs that are not in the Windows folder and not on the allowed list.
# Administrators can always run every program, so this PC cannot be locked out.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Audit", "Enforce")]
    [string]$Mode = "Audit"
)

$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run Set-AllowedPrograms.ps1 from an Administrator PowerShell window."
}

$root = "C:\ProgramData\WorkPilot"
$configPath = Join-Path $root "pilot.json"
if (-not (Test-Path $configPath)) {
    throw "Install the pilot first. $configPath was not found."
}
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$enforcement = "AuditOnly"
if ($Mode -eq "Enforce") { $enforcement = "Enabled" }

function Find-AllowedExecutable {
    param([string]$FileName)
    $known = @{
        "chrome.exe"    = @(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
        )
        "msedge.exe"    = @(
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
        )
        "WINWORD.EXE"   = @(
            "$env:ProgramFiles\Microsoft Office\root\Office16\WINWORD.EXE",
            "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\WINWORD.EXE"
        )
        "EXCEL.EXE"     = @(
            "$env:ProgramFiles\Microsoft Office\root\Office16\EXCEL.EXE",
            "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\EXCEL.EXE"
        )
        "POWERPNT.EXE"  = @(
            "$env:ProgramFiles\Microsoft Office\root\Office16\POWERPNT.EXE",
            "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\POWERPNT.EXE"
        )
        "Acrobat.exe"   = @(
            "$env:ProgramFiles\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            "${env:ProgramFiles(x86)}\Adobe\Acrobat DC\Acrobat\Acrobat.exe"
        )
        "AcroRd32.exe"  = @(
            "$env:ProgramFiles\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            "${env:ProgramFiles(x86)}\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe"
        )
    }
    $key = $FileName
    foreach ($candidateKey in $known.Keys) {
        if ([string]::Equals($candidateKey, $FileName, [StringComparison]::OrdinalIgnoreCase)) {
            $key = $candidateKey
        }
    }
    if ($known.ContainsKey($key)) {
        foreach ($path in $known[$key]) {
            if ($path -and (Test-Path $path)) { return (Resolve-Path $path).Path }
        }
    }
    $appPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$FileName"
    if (Test-Path $appPath) {
        $registered = (Get-ItemProperty $appPath)."(default)"
        if ($registered -and (Test-Path $registered)) { return (Resolve-Path $registered).Path }
    }
    return $null
}

$rules = New-Object System.Collections.Generic.List[string]
$rules.Add(@"
    <FilePathRule Id="fd686d53-ee9b-42f8-b4a8-7c6d4f0d0c11" Name="Allow the Windows folder" Description="Required so Windows can sign in." UserOrGroupSid="S-1-1-0" Action="Allow">
      <Conditions><FilePathCondition Path="%WINDIR%\*" /></Conditions>
    </FilePathRule>
"@)
$rules.Add(@"
    <FilePathRule Id="b7f58856-3e0a-4a4b-9c4e-2a6d8e0f4c22" Name="Allow administrators" Description="Administrators can run every program." UserOrGroupSid="S-1-5-32-544" Action="Allow">
      <Conditions><FilePathCondition Path="*" /></Conditions>
    </FilePathRule>
"@)

$added = New-Object System.Collections.Generic.List[string]
$missing = New-Object System.Collections.Generic.List[string]
foreach ($program in @($config.allowedPrograms)) {
    $fileName = [IO.Path]::GetFileName([string]$program)
    if ([string]::Equals($fileName, "notepad.exe", [StringComparison]::OrdinalIgnoreCase)) {
        continue
    }
    $found = Find-AllowedExecutable $fileName
    if (-not $found) {
        $missing.Add($fileName)
        continue
    }
    $directory = [IO.Path]::GetDirectoryName($found)
    $pathRule = $directory + "\*"
    $id = [guid]::NewGuid().ToString()
    $safeName = [System.Security.SecurityElement]::Escape($fileName)
    $safePath = [System.Security.SecurityElement]::Escape($pathRule)
    $rules.Add(@"
    <FilePathRule Id="$id" Name="Allow $safeName" Description="Pilot allow list" UserOrGroupSid="S-1-1-0" Action="Allow">
      <Conditions><FilePathCondition Path="$safePath" /></Conditions>
    </FilePathRule>
"@)
    $added.Add("$fileName ($directory)")
}

$xml = @"
<AppLockerPolicy Version="1">
  <RuleCollection Type="Appx" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Dll" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Exe" EnforcementMode="$enforcement">
$($rules -join "`n")
  </RuleCollection>
  <RuleCollection Type="Msi" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Script" EnforcementMode="NotConfigured" />
</AppLockerPolicy>
"@

$policyPath = Join-Path $root "applocker-policy.xml"
$backupPath = Join-Path $root "applocker-backup.xml"
if ($PSCmdlet.ShouldProcess("AppLocker", "Set executable rules to $Mode")) {
    if (-not (Test-Path $backupPath)) {
        try {
            Get-AppLockerPolicy -Local -Xml | Set-Content -Path $backupPath -Encoding Unicode
        }
        catch {
            Set-Content -Path $backupPath -Value "<AppLockerPolicy Version=`"1`" />" -Encoding Unicode
        }
    }
    Set-Content -Path $policyPath -Value $xml -Encoding Unicode
    Set-Service -Name AppIDSvc -StartupType Automatic
    Start-Service -Name AppIDSvc -ErrorAction SilentlyContinue
    Set-AppLockerPolicy -XmlPolicy $policyPath
}

Write-Host "AppLocker mode: $Mode"
Write-Host "Allowed folders:"
$added | ForEach-Object { Write-Host "  $_" }
if ($missing.Count -gt 0) {
    Write-Host "Not installed, so not added yet:"
    $missing | ForEach-Object { Write-Host "  $_" }
}
Write-Host "Programs in the Windows folder, including Notepad and PowerShell, still run."
Write-Host "Downloaded programs outside the allowed folders are blocked only after you re-run this script with -Mode Enforce."
