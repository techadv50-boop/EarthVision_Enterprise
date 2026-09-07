# Disable optional automatic backups. Manual BACKUP NOW is unaffected.
param(
    [string]$TaskName = "ServerBackup-Ubuntu"
)

schtasks /Delete /F /TN $TaskName
Write-Host "Automatic backup task removed (or was not present). BACKUP NOW still works."
