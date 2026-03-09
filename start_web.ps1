# Start the retirement calculator web dashboard
# Usage: .\start_web.ps1

Write-Host "Starting Retirement Calculator Web Dashboard..." -ForegroundColor Green
Write-Host ""

# Check if virtual environment exists
if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    . .\venv\Scripts\Activate.ps1
} else {
    Write-Host "Virtual environment not found. Creating..." -ForegroundColor Yellow
    python -m venv venv
    . .\venv\Scripts\Activate.ps1
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    pip install -r requirements.txt
}

Write-Host ""
    if (-not $env:HOST) { $env:HOST = "127.0.0.1" }
    if (-not $env:PORT) { $env:PORT = "8000" }

    Write-Host "Starting web server on http://localhost:$($env:PORT)" -ForegroundColor Green
    Write-Host "Listening on $($env:HOST):$($env:PORT)" -ForegroundColor Cyan
Write-Host "Dashboard will open automatically" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Start the server
    uvicorn app.main:app --reload --host $env:HOST --port $env:PORT
