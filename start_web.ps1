Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$appName = "Retirement Calculator Dashboard"
$hostAddress = "127.0.0.1"
$portNumber = if ($env:PORT) { $env:PORT } else { "8000" }
$url = "http://localhost:$portNumber"

Write-Host "Starting $appName..." -ForegroundColor Green
Write-Host ""

if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "Virtual environment not found. Creating one..." -ForegroundColor Yellow
    python -m venv venv
}

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
. .\venv\Scripts\Activate.ps1

if (-not (Test-Path "venv\Scripts\uvicorn.exe")) {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    python -m pip install -r requirements.txt
}

Write-Host "Listening on ${hostAddress}:${portNumber}" -ForegroundColor Cyan
Write-Host "Opening $url" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

try {
    Start-Process $url | Out-Null
} catch {
    Write-Host "Could not auto-open the browser. Open $url manually." -ForegroundColor Yellow
}

python -m uvicorn app.main:app --reload --host $hostAddress --port $portNumber
