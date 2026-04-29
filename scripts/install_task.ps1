param(
    [string]$TaskName = "GroupTrade Bot",
    [ValidateSet("AtLogOn", "AtStartup")]
    [string]$Trigger = "AtLogOn"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptRoot "start_bot.ps1"

if (-not (Test-Path $startScript)) {
    throw "start_bot.ps1 not found at $startScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -Silent"

if ($Trigger -eq "AtStartup") {
    $triggerObj = New-ScheduledTaskTrigger -AtStartup
} else {
    $triggerObj = New-ScheduledTaskTrigger -AtLogOn
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggerObj `
    -Description "Start GroupTrade bot automatically" `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName ($Trigger)"
