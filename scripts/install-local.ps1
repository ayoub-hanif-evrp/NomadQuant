# Install locked NomadQuant dependencies. Does not reset databases or apply shadow fills.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail([string]$Message) {
    Write-Host "FAILED: $Message"
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python is not on PATH. Install Python 3.12 and reopen PowerShell."
}
$python = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($python -notlike "3.12*") {
    Fail "Python $python was found. NomadQuant requires Python 3.12."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is not on PATH. Install it from https://docs.astral.sh/uv/ and reopen PowerShell."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node.js is not on PATH. Install Node.js 22 or newer."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "npm is not on PATH. Reinstall Node.js."
}

$drive = (Get-Item $Root).PSDrive
$freeGb = [math]::Round($drive.Free / 1GB, 2)
Write-Host "Free space on $($drive.Name): $freeGb GB"
if ($drive.Free -lt 2GB) {
    Fail "Need at least 2 GB free for dependencies and the frontend build."
}

Write-Host "Installing locked Python dependencies..."
& uv sync --all-groups --frozen
if ($LASTEXITCODE -ne 0) { Fail "uv sync failed. Fix the message above, then rerun .\scripts\install-local.ps1" }

Write-Host "Installing frontend dependencies..."
Set-Location (Join-Path $Root "apps\web")
& npm ci
if ($LASTEXITCODE -ne 0) { Fail "npm ci failed. Delete apps\web\node_modules only if you intend to reinstall, then rerun." }
Write-Host "Building the dashboard..."
& npm run build
if ($LASTEXITCODE -ne 0) { Fail "Frontend build failed." }
Set-Location $Root

foreach ($dir in @("data", "data\agent-memos", "data\run", "data\backups")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}

$envFile = Join-Path $Root ".env"
$example = Join-Path $Root ".env.example"
if (Test-Path $envFile) {
    Write-Host ".env already exists. Credentials were left unchanged."
} elseif (Test-Path $example) {
    Copy-Item $example $envFile
    Write-Host "Created .env from .env.example. Paper keys may stay blank."
} else {
    Fail ".env.example is missing."
}

Write-Host "Install complete. Start with .\scripts\start-nomadquant.ps1"
Write-Host "This script did not download models, register scheduled tasks, or apply shadow fills."
