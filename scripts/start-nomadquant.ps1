# Start the local API and the production dashboard. Does not submit orders.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$RunDir = Join-Path $Root "data\run"
$PidFile = Join-Path $RunDir "nomadquant.pids.json"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $handle = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $open = $handle.AsyncWaitHandle.WaitOne(400, $false) -and $client.Connected
        return [bool]$open
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Url([string]$Url) {
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

if (Test-Path $PidFile) {
    $existing = Get-Content $PidFile -Raw | ConvertFrom-Json
    $alive = @($existing.pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($alive.Count -gt 0) {
        Write-Host "NomadQuant is already tracked. Open http://127.0.0.1:3000"
        Write-Host "Stop it with .\scripts\stop-nomadquant.ps1"
        exit 0
    }
}

if (Test-PortOpen 8000) {
    Write-Host "Port 8000 is already in use. Stop the existing API before starting another copy."
    exit 2
}
if (Test-PortOpen 3000) {
    Write-Host "Port 3000 is already in use. Stop the existing dashboard before starting another copy."
    exit 2
}

$build = Join-Path $Root "apps\web\.next"
if (-not (Test-Path $build)) {
    Write-Host "The production dashboard build is missing. Run .\scripts\install-local.ps1 first."
    exit 1
}

$apiLog = Join-Path $RunDir "api.log"
$webLog = Join-Path $RunDir "web.log"
$api = Start-Process -FilePath "uv" -ArgumentList @("run", "--no-sync", "nomadquant-api") -WorkingDirectory $Root -RedirectStandardOutput $apiLog -RedirectStandardError (Join-Path $RunDir "api.err.log") -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1
if ($api.HasExited) {
    Write-Host "The API exited immediately. Read data\run\api.err.log"
    exit 1
}
if (-not (Wait-Url "http://127.0.0.1:8000/health")) {
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    Write-Host "The API did not become healthy. Read data\run\api.err.log"
    exit 1
}

$web = Start-Process -FilePath "npm" -ArgumentList @("run", "start") -WorkingDirectory (Join-Path $Root "apps\web") -RedirectStandardOutput $webLog -RedirectStandardError (Join-Path $RunDir "web.err.log") -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1
if ($web.HasExited) {
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    Write-Host "The dashboard exited immediately. Read data\run\web.err.log"
    exit 1
}
if (-not (Wait-Url "http://127.0.0.1:3000")) {
    Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    Write-Host "The dashboard did not become ready. Read data\run\web.err.log"
    exit 1
}

@{
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    pids = @($api.Id, $web.Id)
    url = "http://127.0.0.1:3000"
} | ConvertTo-Json | Set-Content -Path $PidFile -Encoding utf8

Write-Host "NomadQuant is running at http://127.0.0.1:3000"
Write-Host "API: http://127.0.0.1:8000/health"
Write-Host "Stop with .\scripts\stop-nomadquant.ps1"
Write-Host "Ollama and Alpaca keys are optional. Missing ones stay disconnected."
