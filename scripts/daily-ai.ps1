param(
    [ValidateSet("status")]
    [string]$Action = "status"
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "src"
Write-Host "NomadQuant daily desk: $Action"
Write-Host "This script does not install a Windows task and does not submit an order."
uv run --no-sync python -m nomadquant.daily
exit $LASTEXITCODE
