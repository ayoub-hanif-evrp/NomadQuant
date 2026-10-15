# Read-only check of the local NomadQuant API. This script does not trade.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$base = "http://127.0.0.1:8000"
if ($env:NOMADQUANT_API_URL) {
    $base = $env:NOMADQUANT_API_URL.TrimEnd("/")
}

$failed = $false

function Hide-Sensitive([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) {
        return $Text
    }
    $masked = [regex]::Replace(
        $Text,
        "(?i)(api[_-]?key|api[_-]?secret|secret|authorization|bearer)(\s*[:=]\s*|\s+)(\S+)",
        '$1$2[REDACTED]'
    )
    return [regex]::Replace($masked, "\bPK[A-Z0-9]{10,}\b", "[REDACTED]")
}

function Write-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $label = if ($Ok) { "PASS" } else { "FAIL" }
    Write-Output "$label $Name $(Hide-Sensitive $Detail)"
    if (-not $Ok) {
        $script:failed = $true
    }
}

try {
    $parsed = [Uri]$base
} catch {
    Write-Check "api_url" $false "The API URL is not valid."
    exit 1
}
if ($parsed.Scheme -ne "http" -or ($parsed.Host -ne "127.0.0.1" -and $parsed.Host -ne "localhost")) {
    Write-Check "api_url" $false "This script only calls http://127.0.0.1 or http://localhost."
    exit 1
}

function Get-Endpoint([string]$Path) {
    try {
        $response = Invoke-WebRequest -Uri "$base$Path" -Method GET -UseBasicParsing -TimeoutSec 30
        return @{
            Reachable = $true
            Code      = [int]$response.StatusCode
            Json      = ($response.Content | ConvertFrom-Json)
        }
    } catch {
        if ($null -eq $_.Exception.Response) {
            return @{ Reachable = $false; Kind = "network" }
        }
        return @{ Reachable = $false; Kind = "http" }
    }
}

function Test-Decimal([string]$Value) {
    $parsedNumber = [decimal]0
    return [decimal]::TryParse(
        $Value,
        [Globalization.NumberStyles]::Number,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$parsedNumber
    )
}

$health = Get-Endpoint "/health"
if (-not $health.Reachable) {
    Write-Check "health" $false "The API is not reachable. Start it with: uv run nomadquant-api"
    exit 1
}
$healthOk = $health.Code -eq 200 -and $health.Json.status -eq "ok" -and $health.Json.service -eq "nomadquant"
Write-Check "health" $healthOk "service status is ok"

$status = Get-Endpoint "/api/system/status"
if (-not $status.Reachable -or $status.Code -ne 200) {
    Write-Check "system_status" $false "The status endpoint did not return HTTP 200."
    exit 1
}
$system = $status.Json
Write-Check "trading_mode" ($system.trading_mode -eq "paper" -and $system.paper_only -eq $true) "trading_mode=$($system.trading_mode)"
Write-Check "order_submission" ($system.allow_order_submission -eq $false) "allow_order_submission=$($system.allow_order_submission)"
Write-Check "virtual_capital" ([double]$system.initial_virtual_capital_usd -eq 100) "initial_virtual_capital_usd=$($system.initial_virtual_capital_usd)"
Write-Check "alpaca_host" ($system.alpaca_base_url -eq "https://paper-api.alpaca.markets") "alpaca_base_url is the paper host"
Write-Check "api_host" ($system.api_host -eq "127.0.0.1") "api_host=$($system.api_host)"
Write-Check "database" ($system.database_ok -eq $true) "database_ok=$($system.database_ok)"

$accountCall = Get-Endpoint "/api/broker/account"
$positionsCall = Get-Endpoint "/api/broker/positions"
if (-not $accountCall.Reachable -or -not $positionsCall.Reachable) {
    Write-Check "broker_transport" $false "A local broker endpoint was not reachable."
    exit 1
}
$account = $accountCall.Json
$positions = $positionsCall.Json

if ($account.status -eq "connected") {
    $snapshot = $account.account
    $fieldsOk = $null -ne $snapshot -and
        (Test-Decimal ([string]$snapshot.equity)) -and
        (Test-Decimal ([string]$snapshot.cash)) -and
        (Test-Decimal ([string]$snapshot.buying_power)) -and
        -not [string]::IsNullOrWhiteSpace([string]$snapshot.currency) -and
        -not [string]::IsNullOrWhiteSpace([string]$snapshot.status)
    $detail = "virtual_capital=$($account.virtual_capital_usd)"
    if ($fieldsOk) {
        $detail = "equity=$($snapshot.equity) cash=$($snapshot.cash) buying_power=$($snapshot.buying_power) currency=$($snapshot.currency) account_status=$($snapshot.status) $detail"
    }
    Write-Check "broker_connected" $fieldsOk $detail
    $count = @($positions.positions).Count
    Write-Check "positions" ($positions.status -eq "connected") "open paper positions: $count"
} elseif ($account.status -eq "disconnected") {
    Write-Check "broker_connected" $false "Credentials are not configured. This is not an authentication or network failure."
    Write-Check "positions" ($positions.status -eq "disconnected") "positions follow the disconnected state"
} elseif ($account.failure_kind -eq "authentication") {
    Write-Check "broker_connected" $false "Authentication failed. Create a new Alpaca paper key and update .env. Do not paste keys into chat."
    Write-Check "positions" ($positions.failure_kind -eq "authentication") "positions report the same authentication failure"
} elseif ($account.failure_kind -eq "network") {
    Write-Check "broker_connected" $false "Network failure reaching Alpaca. Check internet access. The only trading host is paper-api.alpaca.markets."
    Write-Check "positions" ($positions.failure_kind -eq "network") "positions report the same network failure"
} elseif ($account.status -eq "rate_limited") {
    Write-Check "broker_connected" $false "Alpaca rate limit. Wait and run this script again."
    Write-Check "positions" ($positions.status -eq "rate_limited") "positions report the same rate limit"
} else {
    Write-Check "broker_connected" $false "Broker status=$($account.status) failure_kind=$($account.failure_kind)"
    Write-Check "positions" ($positions.status -eq $account.status) "positions status=$($positions.status)"
}

$spec = Get-Endpoint "/openapi.json"
if ($spec.Reachable) {
    $paths = @($spec.Json.paths.PSObject.Properties.Name)
    $hasOrder = $false
    foreach ($path in $paths) {
        if ($path.ToLower().Contains("order")) {
            $hasOrder = $true
        }
    }
    Write-Check "no_order_route" (-not $hasOrder) "published routes do not include an order endpoint"
} else {
    Write-Check "no_order_route" $false "OpenAPI document was not reachable."
}

if ($failed) {
    exit 1
}
exit 0
