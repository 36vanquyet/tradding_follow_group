param(
    [string]$TaskName = "GroupTrade Bot",
    [ValidateSet("AtLogOn", "AtStartup")]
    [string]$Trigger = "AtStartup"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptRoot "start_bot.ps1"

if (-not (Test-Path $startScript)) {
    throw "start_bot.ps1 not found at $startScript"
}

if ($Trigger -eq "AtStartup") {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if (-not $isAdmin) {
        throw "AtStartup requires running this script as Administrator."
    }
    $schedule = "ONSTART"
    $runLevel = "HIGHEST"
} else {
    $schedule = "ONLOGON"
    $runLevel = "LIMITED"
}

$taskRun = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -Silent"

& schtasks.exe /Create `
    /TN $TaskName `
    /TR $taskRun `
    /SC $schedule `
    /RL $runLevel `
    /F | Out-Null

Write-Host "Registered scheduled task: $TaskName ($Trigger)"
