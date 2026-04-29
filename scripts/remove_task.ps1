param(
    [string]$TaskName = "GroupTrade Bot"
)

$ErrorActionPreference = "Stop"

& schtasks.exe /Delete /TN $TaskName /F | Out-Null
Write-Host "Removed scheduled task: $TaskName"
