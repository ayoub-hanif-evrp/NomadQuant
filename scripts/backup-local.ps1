# Consistent local backup. Does not upload anything and does not copy .env.
param(
    [string]$Dest = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Dest) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $Dest = Join-Path $Root "data\backups\$stamp"
}
New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
$env:PYTHONPATH = "src"
& uv run --no-sync python -m nomadquant.ops.cli backup --dest $Dest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Backup written to $Dest"
Write-Host "Restore only with the confirm_token from manifest.json and .\scripts\restore-local.ps1"
