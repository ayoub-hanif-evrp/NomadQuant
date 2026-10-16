# Opt-in daily forward shadow worker. Never submits broker orders.
# Does not launch Ollama. Safe to schedule via Task Scheduler after install.
param(
    [switch]$ShadowApply,
    [switch]$DryRun
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
# -ShadowApply opts into simulated ledger apply + outbox — still no broker orders.
if ($ShadowApply -and $DryRun) {
    throw "Use either -DryRun or -ShadowApply, not both."
}
$Mode = if ($ShadowApply) { "shadow-apply" } elseif ($DryRun) { "dry-run" } else { "inspect" }

Write-Log "worker --mode $Mode (ShadowApply=$ShadowApply)"
uv run --no-sync nomadquant-shadow worker --mode $Mode *>> $LogFile
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
