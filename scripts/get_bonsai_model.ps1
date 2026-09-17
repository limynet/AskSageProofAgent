# get_bonsai_model.ps1
# Downloads the Bonsai-1.7B Q1_0 GGUF into models/ and verifies its size.
# Usage:  .\scripts\get_bonsai_model.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root "models"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$target = Join-Path $dir "Bonsai-1.7B-Q1_0.gguf"
if ((Test-Path $target) -and ((Get-Item $target).Length -eq 248302272)) {
    Write-Host "Model already present and verified: $target"
    exit 0
}
$url = "https://huggingface.co/prism-ml/Bonsai-1.7B-gguf/resolve/main/Bonsai-1.7B-Q1_0.gguf"
Write-Host "Downloading Bonsai-1.7B Q1_0 (~237 MB)..."
curl.exe -L --ssl-no-revoke -o $target $url
if ($LASTEXITCODE -ne 0) { Write-Host "Download failed (exit $LASTEXITCODE)." -ForegroundColor Red; exit 1 }
$len = (Get-Item $target).Length
if ($len -ne 248302272) {
    Write-Host "Size mismatch: got $len, expected 248302272. Re-run the script." -ForegroundColor Yellow
    exit 2
}
Write-Host "OK: $target ($len bytes)" -ForegroundColor Green