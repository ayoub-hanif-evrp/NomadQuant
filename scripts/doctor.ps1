# Report local readiness. Does not change databases or submit orders.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$failed = $false

function Report([string]$Name, [string]$Status, [string]$Detail) {
    Write-Host ("{0,-18} {1,-6} {2}" -f $Name, $Status, $Detail)
    if ($Status -eq "FAIL") { $script:failed = $true }
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $py = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($py -like "3.12*") { Report "Python" "PASS" $py } else { Report "Python" "FAIL" $py }
} else { Report "Python" "FAIL" "not on PATH" }

if (Get-Command uv -ErrorAction SilentlyContinue) { Report "uv" "PASS" "present" } else { Report "uv" "FAIL" "not on PATH" }
if (Get-Command node -ErrorAction SilentlyContinue) { Report "Node" "PASS" (& node -v) } else { Report "Node" "FAIL" "not on PATH" }
if (Test-Path ".env") { Report ".env" "PASS" "present; values not printed" } else { Report ".env" "WARN" "missing; install-local.ps1 can create it" }
if (Test-Path "apps\web\.next") { Report "Web build" "PASS" "present" } else { Report "Web build" "WARN" "run install-local.ps1" }

$drive = (Get-Item $Root).PSDrive
Report "Disk" "PASS" ("{0:N2} GB free" -f ($drive.Free / 1GB))

foreach ($name in @("data\market.sqlite", "data\research.sqlite", "data\shadow.sqlite", "data\risk.sqlite", "data\agents.sqlite")) {
    if (Test-Path (Join-Path $Root $name)) { Report $name "PASS" "present" } else { Report $name "WARN" "absent; the app still starts" }
}

function Test-Http([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode
    } catch { return $null }
}

$api = Test-Http "http://127.0.0.1:8000/health"
if ($api) { Report "API" "PASS" "http://127.0.0.1:8000/health" } else { Report "API" "WARN" "not running" }
$web = Test-Http "http://127.0.0.1:3000"
if ($web) { Report "Dashboard" "PASS" "http://127.0.0.1:3000" } else { Report "Dashboard" "WARN" "not running" }

try {
    $ollama = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3
    Report "Ollama" "PASS" "local tags endpoint responded"
} catch {
    Report "Ollama" "WARN" "not reachable; research agents stay disconnected"
}

if ($failed) { exit 1 }
Write-Host "Doctor finished. Warnings are usable disconnected states, not order failures."
