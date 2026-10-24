# Start the API and dashboard against a temporary directory. Does not read .env.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Fail([string]$Message) {
    Write-Host "FAILED: $Message"
    exit 1
}

function Stop-Boot([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    if (-not $Process.HasExited) {
        & taskkill /PID $Process.Id /T /F 2>$null | Out-Null
        $Process.WaitForExit(3000) | Out-Null
    }
}

function Test-PortFree([int]$Port) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("nomadquant-boot-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $temp | Out-Null
$envPath = Join-Path $Root ".env"
$envExisted = Test-Path $envPath
$envHash = $null
if ($envExisted) { $envHash = (Get-FileHash -Algorithm SHA256 $envPath).Hash }
$dataRoot = Join-Path $Root "data"
$dataBefore = @()
if (Test-Path $dataRoot) {
    $dataBefore = @(Get-ChildItem $dataRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
}

$apiPort = 8011
if (Test-PortFree 8000) { $apiPort = 8000 }
$webPort = 3011
if (-not (Test-PortFree $webPort)) { $webPort = 3012 }

$api = $null
$web = $null

try {
    $apiInfo = New-Object System.Diagnostics.ProcessStartInfo
    $apiInfo.FileName = (Get-Command uv).Source
    $apiInfo.Arguments = "run --no-sync python -m nomadquant.ops.isolated_boot"
    $apiInfo.WorkingDirectory = $Root
    $apiInfo.UseShellExecute = $false
    $apiInfo.RedirectStandardOutput = $true
    $apiInfo.RedirectStandardError = $true
    $apiInfo.EnvironmentVariables["PYTHONPATH"] = Join-Path $Root "src"
    foreach ($name in @("ALPACA_API_KEY", "ALPACA_API_SECRET", "SMTP_PASSWORD")) {
        [void]$apiInfo.EnvironmentVariables.Remove($name)
    }
    $apiInfo.EnvironmentVariables["TRADING_MODE"] = "paper"
    $apiInfo.EnvironmentVariables["ALLOW_ORDER_SUBMISSION"] = "false"
    $apiInfo.EnvironmentVariables["INITIAL_VIRTUAL_CAPITAL_USD"] = "100"
    $apiInfo.EnvironmentVariables["API_HOST"] = "127.0.0.1"
    $apiInfo.EnvironmentVariables["API_PORT"] = "$apiPort"
    $apiInfo.EnvironmentVariables["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
    $apiInfo.EnvironmentVariables["OLLAMA_MODEL"] = ""
    $apiInfo.EnvironmentVariables["DATABASE_PATH"] = Join-Path $temp "nomadquant.db"
    $apiInfo.EnvironmentVariables["MARKET_DATA_PATH"] = Join-Path $temp "market.sqlite"
    $apiInfo.EnvironmentVariables["RESEARCH_PATH"] = Join-Path $temp "research.sqlite"
    $apiInfo.EnvironmentVariables["AGENTS_PATH"] = Join-Path $temp "agents.sqlite"
    $apiInfo.EnvironmentVariables["AGENT_MEMO_ROOT"] = Join-Path $temp "agent-memos"
    $apiInfo.EnvironmentVariables["AGENT_BENCHMARK_PATH"] = Join-Path $temp "agent-benchmarks.sqlite"
    $apiInfo.EnvironmentVariables["RISK_PATH"] = Join-Path $temp "risk.sqlite"
    $apiInfo.EnvironmentVariables["SHADOW_PATH"] = Join-Path $temp "shadow.sqlite"
    $apiInfo.EnvironmentVariables["PAPER_PATH"] = Join-Path $temp "paper_orders.sqlite"
    $apiInfo.EnvironmentVariables["DAILY_PATH"] = Join-Path $temp "daily_pilot.sqlite"
    $apiInfo.EnvironmentVariables["APPROVAL_PATH"] = Join-Path $temp "approvals.sqlite"
    $apiInfo.EnvironmentVariables["APPROVAL_OUTBOX_DIR"] = Join-Path $temp "approval-outbox"
    $apiInfo.EnvironmentVariables["NEWS_PATH"] = Join-Path $temp "news.sqlite"
    $api = [System.Diagnostics.Process]::Start($apiInfo)
    $apiOut = $api.StandardOutput.ReadToEndAsync()
    $apiErr = $api.StandardError.ReadToEndAsync()

    $health = $null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($api.HasExited) { break }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$apiPort/health"
            break
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $health -or $health.status -ne "ok" -or $health.service -ne "nomadquant") {
        if ($api.HasExited) {
            [void]$apiErr.Wait(2000)
            Write-Host $apiErr.Result
        }
        Fail "API health did not answer on port $apiPort."
    }
    $status = Invoke-RestMethod "http://127.0.0.1:$apiPort/api/system/status"
    if ($status.trading_mode -ne "paper") { Fail "Trading mode was $($status.trading_mode)." }
    if ($status.allow_order_submission) { Fail "Order submission was enabled." }
    if ($status.paper_only -ne $true) { Fail "Paper-only was not set." }
    if ($status.credentials_configured) { Fail "Isolated boot saw broker credentials." }
    if ($status.broker_status -ne "disconnected") { Fail "Broker status was $($status.broker_status)." }
    if ([double]$status.initial_virtual_capital_usd -ne 100) { Fail "Capital was not 100." }

    $webInfo = New-Object System.Diagnostics.ProcessStartInfo
    $webInfo.FileName = (Get-Command node).Source
    $webInfo.Arguments = "node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port $webPort"
    $webInfo.WorkingDirectory = Join-Path $Root "apps\web"
    $webInfo.UseShellExecute = $false
    $webInfo.RedirectStandardOutput = $true
    $webInfo.RedirectStandardError = $true
    $web = [System.Diagnostics.Process]::Start($webInfo)
    $webOut = $web.StandardOutput.ReadToEndAsync()
    $webErr = $web.StandardError.ReadToEndAsync()
    $page = $null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($web.HasExited) { break }
        try {
            $page = Invoke-WebRequest "http://127.0.0.1:$webPort/paper" -UseBasicParsing
            if ($page.StatusCode -eq 200) { break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $page -or $page.StatusCode -ne 200) { Fail "Dashboard /paper did not answer on port $webPort." }
    Write-Host "FRESH BOOT PASSED api=$apiPort web=$webPort broker=disconnected"
} finally {
    Stop-Boot $web
    Stop-Boot $api
    foreach ($task in @($apiOut, $apiErr, $webOut, $webErr)) {
        if ($null -ne $task) { [void]$task.Wait(8000) }
    }
    $envNow = Test-Path $envPath
    if ($envNow -ne $envExisted) { Fail ".env presence changed." }
    if ($envExisted -and (Get-FileHash -Algorithm SHA256 $envPath).Hash -ne $envHash) { Fail ".env contents changed." }
    foreach ($name in @("nomadquant.db", "market.sqlite", "paper_orders.sqlite", "daily_pilot.sqlite", "research.sqlite")) {
        $path = Join-Path $dataRoot $name
        if (-not ($dataBefore -contains $path) -and (Test-Path $path)) {
            Fail "Isolated boot created repository data file $name."
        }
    }
}
