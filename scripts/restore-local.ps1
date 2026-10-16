# Restore a verified backup. Requires the exact confirm token and a stopped app.
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Confirm
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "This replaces local research and shadow databases with the backup."
Write-Host "A safety copy is written under data\restore-safety before files are replaced."
$env:PYTHONPATH = "src"
& uv run --no-sync python -m nomadquant.ops.cli restore --source $Source --confirm $Confirm
exit $LASTEXITCODE
