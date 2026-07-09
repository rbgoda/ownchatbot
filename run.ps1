# ownchatbot — Windows PowerShell launcher.  Right-click → Run with PowerShell,
# or:  powershell -ExecutionPolicy Bypass -File run.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt
if (-not (Test-Path .env) -and (Test-Path .env.example)) { Copy-Item .env.example .env; Write-Host "Created .env (optional: add an LLM key)" }
Write-Host ""
Write-Host "  ownchatbot running ->  http://localhost:8200   (admin)"
Write-Host "                         http://localhost:8200/demo (test the widget)"
Write-Host "  Press Ctrl+C to stop."
Write-Host ""
& $py -m uvicorn ownchatbot.server:app --host 127.0.0.1 --port 8200
