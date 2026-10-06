# One-time setup: venv, packages, Chromium, .env
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    python -m venv venv
}

& "venv\Scripts\python.exe" -m pip install --upgrade pip
& "venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& "venv\Scripts\python.exe" -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "playwright install failed" }

if (-not (Test-Path ".env")) {
    Copy-Item "env.example" ".env"
    Write-Host "Created .env - fill in PORTAL_USER, PORTAL_PASS, ANTHROPIC_API_KEY, TELEGRAM_* before the first run."
}

Write-Host "Setup done. Next: powershell -ExecutionPolicy Bypass -File install_task.ps1"
