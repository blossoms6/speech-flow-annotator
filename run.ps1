$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m pip install -q -r requirements.txt

Write-Host "Starting Speech Flow Annotator at http://127.0.0.1:8765"
Start-Process "http://127.0.0.1:8765"
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
