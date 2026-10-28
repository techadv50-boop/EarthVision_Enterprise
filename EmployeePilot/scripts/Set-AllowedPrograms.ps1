# Program blocking is retired. Running this script no longer changes which programs can start.
# Word, Excel, and PowerPoint stay allowed for the employee.
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

if ($PSCmdlet.ShouldProcess("Office", "Leave Word, Excel, and PowerPoint allowed")) {
    Remove-Item -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\SrpV2" -Recurse -Force -ErrorAction SilentlyContinue
    Stop-Service -Name AppIDSvc -Force -ErrorAction SilentlyContinue
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\AppIDSvc" -Name Start -Value 4 -Type DWord -ErrorAction SilentlyContinue
}

Write-Host "Program blocking is off. Word, Excel, and PowerPoint can open."
Write-Host "The requested mode ($Mode) is ignored so Office is not blocked again."
