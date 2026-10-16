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

$started = @{}
if ($payload.processes) {
    foreach ($item in @($payload.processes)) {
        $started[[string]$item.pid] = [string]$item.started_at
    }
}

function Stop-Tree([int]$ProcessId, [string]$StartedAt, [bool]$ParentVerified) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "PID $ProcessId is not running."
        return
    }
    if (-not $ParentVerified) {
        if (-not $StartedAt -or -not $proc.CreationDate) {
            Write-Host "PID $ProcessId has no recorded start time. It was not stopped."
            return
        }
        $actual = $proc.CreationDate.ToUniversalTime().ToString("o")
        if ($actual.Substring(0, 19) -ne $StartedAt.Substring(0, 19)) {
            Write-Host "PID $ProcessId belongs to a different process. It was not stopped."
            return
        }
    }
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-Tree ([int]$child.ProcessId) "" $true
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID $ProcessId ($($proc.Name))"
}

foreach ($pidValue in $pids) {
    $key = [string][int]$pidValue
    Stop-Tree ([int]$pidValue) ([string]$started[$key]) $false
}
Start-Sleep -Seconds 2
Remove-Item $PidFile -Force
Write-Host "Tracked NomadQuant processes were stopped. Other Python, Node, and Ollama processes were left running."
