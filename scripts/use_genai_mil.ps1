# use_genai_mil.ps1 - wire the GenAI-MIL (IL5) outlet key into the app.
#
# Stores the GenAI-MIL API key in secrets/outlets.env (gitignored, never
# committed) and verifies the outlet entry exists in configs/outlets.json.
# No rebuild needed: configs/ and secrets/ are bind-mounted; refresh the
# dashboard browser tab afterwards and pick "GenAI-MIL (IL5)" in a node
# editor's Outlet dropdown.
#
# Usage:  .\scripts\use_genai_mil.ps1          # prompts for the key
#         .\scripts\use_genai_mil.ps1 -Key ... # (not recommended; visible)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

param(
    [string]$Key = "",
    [string]$Model = "gemini-2.5-flash"
)

# 1. Key input (masked unless provided as an argument).
if ([string]::IsNullOrWhiteSpace($Key)) {
    Write-Host "Paste the GenAI-MIL API key (input is hidden):"
    $Key = Read-Host -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Key)
    try { $Key = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if ([string]::IsNullOrWhiteSpace($Key)) {
    Write-Host "No key entered; nothing changed." -ForegroundColor Yellow
    exit 1
}

# 2. Write to secrets/outlets.env, preserving any existing lines.
$secretsDir = Join-Path $root "secrets"
New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null
$envPath = Join-Path $secretsDir "outlets.env"
$lines = if (Test-Path $envPath) { @(Get-Content $envPath) } else { @() }
$out = @()
$found = $false
foreach ($ln in $lines) {
    if ($ln -match '^\s*GENAI_MIL_API_KEY\s*=') { $out += "GENAI_MIL_API_KEY=$Key"; $found = $true }
    elseif ($ln -match '^\s*GENAI_MIL_MODEL\s*=') { $out += "GENAI_MIL_MODEL=$Model" }
    else { $out += $ln }
}
if (-not $found) { $out += "GENAI_MIL_API_KEY=$Key" }
Set-Content -Path $envPath -Value $out -Encoding utf8

# 3. Verify the GenAI-MIL outlet entry exists (it ships with the repo; if
#    missing, add it so the registry stays valid).
$outletsPath = Join-Path $root "configs\outlets.json"
$reg = Get-Content $outletsPath -Raw | ConvertFrom-Json
$has = @($reg.outlets | Where-Object { $_.key -eq "genai-mil" }).Count -gt 0
if (-not $has) {
    $reg.outlets += [pscustomobject]@{
        key = "genai-mil"; title = "GenAI-MIL (IL5)"
        base_url_env = "GENAI_MIL_BASE_URL"; base_url_default = "https://api.genai.mil/v1"
        model_env = "GENAI_MIL_MODEL"; model_default = $Model
        api_key_env = "GENAI_MIL_API_KEY"; api_key_default = ""
    }
    $reg | ConvertTo-Json -Depth 6 | Set-Content -Path $outletsPath -Encoding utf8
    Write-Host "Added missing genai-mil outlet entry to configs/outlets.json" -ForegroundColor Green
}

# 4. Sanity check: the loaded resolver sees the key.
& (Join-Path $root ".venv\Scripts\python.exe") -c "import sys; sys.path.insert(0, r'$root\src'); import outlets; c=outlets.resolve_outlet('genai-mil'); print('base_url:', c['base_url']); print('model:', c['model']); print('key set:', bool(c['api_key']))"

Write-Host ""
Write-Host "Done. Refresh the dashboard browser tab, then in any node" -ForegroundColor Cyan
Write-Host "editor set Outlet = GenAI-MIL (IL5) and Save. Key is stored in" -ForegroundColor Cyan
Write-Host "secrets/outlets.env and is gitignored (never committed)." -ForegroundColor Cyan