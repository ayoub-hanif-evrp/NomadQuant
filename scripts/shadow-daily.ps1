# Opt-in daily forward shadow check. Never submits broker orders.
# Does not launch Ollama. Safe to schedule via Task Scheduler after install.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LockDir = Join-Path $Root "data"
$LockFile = Join-Path $LockDir "shadow_cycle.lock"
$LogDir = Join-Path $Root "data\shadow_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "shadow-$stamp.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format o) $msg"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

# America/New_York weekday + holiday awareness is delegated to preflight/cycle
# (NYSE calendar in Python). This wrapper only avoids overlapping runs.

if (Test-Path $LockFile) {
    $age = (Get-Date) - (Get-Item $LockFile).LastWriteTime
    if ($age.TotalHours -lt 2) {
        Write-Log "SKIP: lock held ($LockFile age=$($age.TotalMinutes)m)"
        exit 0
    }
    Write-Log "WARN: stale lock removed"
    Remove-Item $LockFile -Force
}

New-Item -ItemType File -Path $LockFile -Force | Out-Null
try {
    Write-Log "preflight"
    uv run --no-sync nomadquant-shadow preflight *>> $LogFile
    if ($LASTEXITCODE -ne 0) { throw "preflight exit $LASTEXITCODE" }

    Write-Log "cycle dry-run"
    uv run --no-sync nomadquant-shadow cycle --mode dry-run *>> $LogFile
    if ($LASTEXITCODE -ne 0) { throw "dry-run exit $LASTEXITCODE" }

    Write-Log "reconcile"
    uv run --no-sync nomadquant-shadow reconcile *>> $LogFile
    if ($LASTEXITCODE -ne 0) { throw "reconcile exit $LASTEXITCODE" }

    Write-Log "OK"
    exit 0
}
catch {
    Write-Log "ERROR: $_"
    exit 1
}
finally {
    if (Test-Path $LockFile) { Remove-Item $LockFile -Force }
}
