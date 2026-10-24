# Run the local release checks. Does not read .env, submit an order, or restore a database.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail([string]$Message) {
    Write-Host "FAILED: $Message"
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "Python is not on PATH." }
$python = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($python -notlike "3.12*") { Fail "Python $python is not 3.12." }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv is not on PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js is not on PATH." }
if (-not (Test-Path "uv.lock")) { Fail "uv.lock is missing." }
if (-not (Test-Path "apps\web\package-lock.json")) { Fail "apps\web\package-lock.json is missing." }
Write-Host "Toolchain python=$python node=$((node -v)). Isolated tests use temporary databases."

$env:PYTHONPATH = "src"
& uv run --no-sync ruff check .
if ($LASTEXITCODE -ne 0) { Fail "ruff reported a problem." }
& uv run --no-sync mypy src
if ($LASTEXITCODE -ne 0) { Fail "mypy reported a problem." }
& uv run --no-sync pytest -q
if ($LASTEXITCODE -ne 0) { Fail "pytest reported a failure." }

Set-Location (Join-Path $Root "apps\web")
& npm run lint
if ($LASTEXITCODE -ne 0) { Fail "eslint reported a problem." }
& npx tsc --noEmit
if ($LASTEXITCODE -ne 0) { Fail "TypeScript reported a problem." }
if (-not (Test-Path ".next\BUILD_ID")) {
    Fail "The dashboard build is missing. Run npm run build in apps\web, then rerun this script."
}
& npm run operator-browser
if ($LASTEXITCODE -ne 0) { Fail "The browser check failed." }
Set-Location $Root
Write-Host "RELEASE CHECK PASSED"
Write-Host "RESEARCH_QUALIFIED and PAPER_VALIDATED are separate and are not granted by this script."
