# Start EarthVision FastAPI backend (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"

Set-Location $Backend

if (-not (Test-Path ".\.venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"

Write-Host "Installing backend dependencies..."
pip install -r requirements.txt --quiet

$env:PYTHONPATH = $Backend
if (-not $env:SECRET_KEY) {
    $env:SECRET_KEY = "dev-secret-key-change-in-production-min-32-chars"
}

Write-Host "Starting uvicorn on http://0.0.0.0:8000 ..."
Write-Host "API docs: http://localhost:8000/api/docs"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
