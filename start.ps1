# Starts the image generator and a Cloudflare quick tunnel, then shows the public link
# (also copied to the clipboard and saved in tunnel-link.txt). Ctrl+C stops both.
#
#   .\start.ps1               start everything
#   .\start.ps1 -NoBrowser    do not open the Share tab in the browser
#   .\start.ps1 -Port 3001    use another port (default: PORT from .env, or 3000)
#
# Double-click start.cmd to run this without changing PowerShell's execution policy.

param(
    [int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$StopAfterLink  # for testing: stop again as soon as the link is known
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Use the current PATH from Windows, so cloudflared is found even in a terminal opened before installing it.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function Fail($message) {
    Write-Host ""
    Write-Host "  $message" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# --- Checks ---
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Fail "The app is not installed yet. Run 'poetry install' once, then try again." }
$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) { Fail "cloudflared is not installed. Run 'winget install Cloudflare.cloudflared' once, then try again." }
if (-not (Test-Path '.env')) { Fail "No .env file found. Copy .env.example to .env and fill it in first." }

if ($Port -eq 0) {
    $portLine = Select-String -Path '.env' -Pattern '^\s*PORT\s*=\s*(\d+)' | Select-Object -First 1
    $Port = if ($portLine) { [int]$portLine.Matches[0].Groups[1].Value } else { 3000 }
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Fail "Port $Port is already in use (is the app already running?). Stop it first, or use: .\start.ps1 -Port 3001"
}

$logs = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$appLog = Join-Path $logs 'app.log'
$appErr = Join-Path $logs 'app-errors.log'
$tunnelLog = Join-Path $logs 'cloudflared.log'
$tunnelOut = Join-Path $logs 'cloudflared-out.log'
Remove-Item $appLog, $appErr, $tunnelLog, $tunnelOut -ErrorAction SilentlyContinue

$app = $null
$tunnel = $null
try {
    # --- Start the app and the tunnel in the background ---
    Write-Host "Starting the app on http://localhost:$Port ..."
    $env:PORT = "$Port"
    $app = Start-Process $python -ArgumentList '-m', 'image_generator' -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $appLog -RedirectStandardError $appErr
    Write-Host "Starting the Cloudflare tunnel ..."
    $tunnel = Start-Process $cloudflared -ArgumentList 'tunnel', '--url', "http://localhost:$Port" -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelLog

    # --- Wait for the app and for the public link (cloudflared prints it in its log) ---
    $link = $null
    $appReady = $false
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not ($link -and $appReady)) {
        Start-Sleep -Milliseconds 500
        if ($app.HasExited) { Fail "The app stopped right away. See logs\app-errors.log:`n$(Get-Content $appErr -Tail 15 | Out-String)" }
        if ($tunnel.HasExited) { Fail "cloudflared stopped right away. See logs\cloudflared.log:`n$(Get-Content $tunnelLog -Tail 15 | Out-String)" }
        if (-not $link -and (Test-Path $tunnelLog)) {
            $match = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
            if ($match) { $link = $match.Matches[0].Value }
        }
        if (-not $appReady) {
            try { Invoke-WebRequest "http://127.0.0.1:$Port/api/session" -UseBasicParsing -TimeoutSec 2 | Out-Null; $appReady = $true } catch {}
        }
    }
    if (-not $appReady) { Fail "The app did not start within 60 seconds. See logs\app-errors.log." }
    if (-not $link) { Fail "No tunnel link after 60 seconds. See logs\cloudflared.log." }

    # --- Make the link easy to use ---
    Set-Clipboard -Value $link
    Set-Content -Path (Join-Path $PSScriptRoot 'tunnel-link.txt') -Value $link -Encoding ascii
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor Green
    Write-Host "   Public link (already copied to your clipboard, Ctrl+V to paste):" -ForegroundColor Green
    Write-Host ""
    Write-Host "     $link" -ForegroundColor White
    Write-Host ""
    Write-Host "   For you (QR code, Share tab):  $link/#share"
    Write-Host "   On this computer:             http://localhost:$Port"
    Write-Host "   The link is also saved in tunnel-link.txt."
    Write-Host "  ================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  It can take up to a minute before the link works everywhere."
    Write-Host "  Keep this window open. Press Ctrl+C to stop the app and the tunnel."
    Write-Host ""

    if (-not $NoBrowser) { Start-Process "$link/#share" }
    if ($StopAfterLink) { return }

    # --- Keep running until Ctrl+C, or until one of the two stops by itself ---
    while (-not $app.HasExited -and -not $tunnel.HasExited) { Start-Sleep -Seconds 1 }
    if ($app.HasExited) { Write-Host "The app stopped. See logs\app-errors.log." -ForegroundColor Red }
    if ($tunnel.HasExited) { Write-Host "The tunnel stopped. See logs\cloudflared.log." -ForegroundColor Red }
}
finally {
    # Also runs on Ctrl+C: stop whatever is still running.
    foreach ($process in @($tunnel, $app)) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Stopped the app and the tunnel."
}
