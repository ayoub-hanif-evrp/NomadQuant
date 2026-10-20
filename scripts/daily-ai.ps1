param(
    [ValidateSet("status")]
    [string]$Action = "status"
)

Write-Host "NomadQuant daily AI paper pilot: $Action"
Write-Host "This script does not install a Windows task and does not submit an order."
Write-Host "A future local schedule would run only while this computer is on."
Write-Host "Missed sessions are not backfilled and are not permission to trade late."
exit 0
