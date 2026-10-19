# Opt-in daily forward shadow worker. Never submits broker orders.
# Does not launch Ollama. Safe to schedule via Task Scheduler after install.
param(
    [switch]$ShadowApply,
    [switch]$DryRun,
    [switch]$Sync
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $Root "data\shadow_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "shadow-$stamp.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format o) $msg"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

# Default: inspect (preflight + reconcile only). -DryRun runs cycle dry-run.
# -ShadowApply opts into simulated ledger apply + outbox. Still no broker orders.
if ($ShadowApply -and $DryRun) {
    throw "Use either -DryRun or -ShadowApply, not both."
}
$Mode = if ($ShadowApply) { "shadow-apply" } elseif ($DryRun) { "dry-run" } else { "inspect" }

$env:PYTHONPATH = Join-Path $Root "src"
$gateJson = uv run --no-sync python -c "import json; from datetime import UTC, datetime; from nomadquant.shadow.schedule import ny_daily_gate; print(json.dumps(ny_daily_gate(datetime.now(UTC))))"
if ($LASTEXITCODE -ne 0) { throw "NY schedule gate failed" }
$gate = $gateJson | ConvertFrom-Json
Write-Log "ny_gate eligible=$($gate.eligible) reason=$($gate.reason) ny=$($gate.ny_local)"
if (-not $gate.eligible) {
    Write-Log "SKIP: not an eligible America/New_York daily window"
    exit 0
}

if ($Sync -and $ShadowApply) {
    Write-Log "REFUSING: historical sync and shadow-apply are separate decisions"
    exit 2
}
if ($Sync) {
    Write-Log "historical SIP sync plus inspect. This does not trade and does not shadow-apply."
    uv run --no-sync nomadquant-shadow daily --mode inspect --sync *>> $LogFile
} else {
    Write-Log "worker --mode $Mode (ShadowApply=$ShadowApply DryRun=$DryRun Sync=false)"
    uv run --no-sync nomadquant-shadow worker --mode $Mode *>> $LogFile
}
$code = $LASTEXITCODE
if ($code -eq 2) {
    Write-Log "RECOVERY_REQUIRED: run nomadquant-shadow recover before shadow-apply"
    exit 2
}
if ($code -ne 0) {
    Write-Log "ERROR: worker exit $code"
    exit $code
}
Write-Log "OK"
exit 0
