# Stop only the processes recorded by start-nomadquant.ps1.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "data\run\nomadquant.pids.json"
if (-not (Test-Path $PidFile)) {
    Write-Host "No tracked NomadQuant processes. Nothing was stopped."
    exit 0
}

$payload = Get-Content $PidFile -Raw | ConvertFrom-Json
$pids = @($payload.pids)

function Stop-Tree([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-Tree ([int]$child.ProcessId)
    }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped PID $ProcessId ($($proc.ProcessName))"
    }
}

foreach ($pidValue in $pids) {
    Stop-Tree ([int]$pidValue)
}
Start-Sleep -Seconds 2
Remove-Item $PidFile -Force
Write-Host "Tracked NomadQuant processes were stopped. Other Python, Node, and Ollama processes were left running."
