param(
    [switch]$Reload,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$uvicornArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8080"
)

if ($Reload) {
    $uvicornArgs += "--reload"
}

if ($Silent) {
    $uvicornArgs += "--log-level"
    $uvicornArgs += "warning"
    $uvicornArgs += "--no-access-log"
    $logDir = Join-Path $repoRoot "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir "bot.out.log"
    $stderrLog = Join-Path $logDir "bot.err.log"
    Start-Process -FilePath $python -ArgumentList $uvicornArgs -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
} else {
    & $python @uvicornArgs
}
