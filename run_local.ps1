# run_local.ps1
# Starts the AskSage Proof Agent dashboard locally (no Docker) for review.
#
# Usage:
#   .\run_local.ps1            # start on port 8501
#   .\run_local.ps1 -Port 8600 # start on a different port
#
# The dashboard runs without a live LLM. The deterministic APA 7 / Army
# publication rule engine works fully offline; the LLM passes and the
# Playground require a reachable engine (local llama-server or a custom
# OpenAI-compatible endpoint).

param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Virtual environment not found at .venv" -ForegroundColor Red
    Write-Host "Create it first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

# Default the local outlet to a host-reachable endpoint for non-Docker runs.
if (-not $env:LOCAL_API_BASE) { $env:LOCAL_API_BASE = "http://localhost:8080/v1" }
if (-not $env:LOCAL_MODEL)    { $env:LOCAL_MODEL    = "bonsai-1.7b" }

Write-Host ""
Write-Host "AskSage Proof Agent - local dashboard" -ForegroundColor Cyan
Write-Host "  URL:    http://localhost:$Port"
Write-Host "  Health: http://localhost:$Port/health"
Write-Host "  Local engine endpoint: $env:LOCAL_API_BASE ($env:LOCAL_MODEL)"
Write-Host ""
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

$env:PORT = "$Port"
& $python "dashboard.py"
