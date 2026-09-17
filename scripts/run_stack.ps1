# run_stack.ps1
# One-command bootstrap: ensures the engine image exists, then starts the
# whole stack. Run from anywhere; uses the project root.
# Usage:  .\scripts\run_stack.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. Model present?
$model = Join-Path $root "models\Bonsai-1.7B-Q1_0.gguf"
if (-not (Test-Path $model)) {
    Write-Host "Model not found. Run .\scripts\get_bonsai_model.ps1 first." -ForegroundColor Yellow
    exit 1
}

# 2. Engine image present? (docker images may need the daemon; treat any
#    ambiguity as missing and let the build fail loudly.)
$image = docker images -q maple-llm-server:latest 2>$null
if (-not $image) {
    if (-not (Test-Path (Join-Path $root "llama.cpp\.devops\cpu.Dockerfile"))) {
        Write-Host "llama.cpp source not found. See docs/NEW_USERS_GUIDE.md section 3." -ForegroundColor Red
        exit 1
    }
    Write-Host "Building the engine image (one time, 10-30 min)..."
    Push-Location (Join-Path $root "llama.cpp")
    docker build -t maple-llm-server:latest --target server -f .devops/cpu.Dockerfile . | Out-Host
    Pop-Location
}

# 3. Start the stack.
Write-Host "Starting the stack..."
docker compose -f (Join-Path $root "docker-compose.yml") up -d --build | Out-Host
Write-Host ""
Write-Host "Dashboard: http://localhost:8501"
Write-Host "Engine:    http://localhost:8080  (model bonsai-1.7b)"