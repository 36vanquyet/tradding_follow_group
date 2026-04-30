param(
    [string]$Url = "http://127.0.0.1:8080",
    [switch]$Silent,
    [string]$CloudflaredPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

function Resolve-CloudflaredPath {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (Test-Path $ExplicitPath) {
            return (Resolve-Path $ExplicitPath).Path
        }
        throw "cloudflared not found at explicit path: $ExplicitPath"
    }

    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "C:\Program Files\cloudflared\cloudflared.exe",
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Programs\cloudflared\cloudflared.exe",
        "C:\Cloudflared\bin\cloudflared.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    throw "cloudflared.exe not found. Install it with: winget install --id Cloudflare.cloudflared"
}

$cloudflared = Resolve-CloudflaredPath -ExplicitPath $CloudflaredPath

$args = @("tunnel", "--url", $Url)

if ($Silent) {
    $logDir = Join-Path $repoRoot "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir "cloudflared.out.log"
    $stderrLog = Join-Path $logDir "cloudflared.err.log"
    $urlFile = Join-Path $logDir "tunnel.url.txt"
    Start-Process -FilePath $cloudflared -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null

    $deadline = (Get-Date).AddSeconds(30)
    $url = $null
    while (-not $url -and (Get-Date) -lt $deadline) {
        if (Test-Path $stderrLog) {
            $content = Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue
            if ($content) {
                $match = [regex]::Match($content, 'https://[^\s\]\"]+trycloudflare\.com[^\s\]\"]*')
                if ($match.Success) {
                    $url = $match.Value.Trim()
                    Set-Content -Path $urlFile -Value $url -Encoding ASCII
                    Write-Host "Tunnel URL: $url"
                    break
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $url) {
        Write-Warning "Cloudflare Tunnel started, but the public URL was not captured yet. Check $stderrLog."
    }
} else {
    & $cloudflared @args
}
