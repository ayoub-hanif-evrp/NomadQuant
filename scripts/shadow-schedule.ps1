# Opt-in Windows Task Scheduler helper for NomadQuant shadow daily checks.
# NEVER schedules broker orders. Does NOT auto-install; call install explicitly.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("install", "status", "disable", "run-once")]
    [string]$Action,
    [switch]$ShadowApply,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$TaskName = "NomadQuantShadowDaily"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $PSScriptRoot "shadow-daily.ps1"

function Get-NextNyWindow {
    # Authoritative next 17:45 America/New_York on an NYSE session.
    # Host local time is display-only; the daily script re-checks the gate.
    $env:PYTHONPATH = Join-Path $Root "src"
    $json = uv run --no-sync python -c "import json; from datetime import UTC, datetime; from nomadquant.shadow.schedule import next_ny_window; print(json.dumps(next_ny_window(datetime.now(UTC))))"
    if ($LASTEXITCODE -ne 0) { throw "Could not compute the next America/New_York window." }
    return $json | ConvertFrom-Json
}

switch ($Action) {
    "install" {
        $when = Get-NextNyWindow
        $dailyArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
        if ($ShadowApply) { $dailyArgs += " -ShadowApply" }
        elseif ($DryRun) { $dailyArgs += " -DryRun" }
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $dailyArgs
        # Repeat through the day. shadow-daily.ps1 applies the NYSE/New York gate,
        # so daylight-saving changes do not freeze a host-local 17:45.
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
            -RepetitionInterval (New-TimeSpan -Minutes 30) `
            -RepetitionDuration (New-TimeSpan -Days 999)
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -MultipleInstances IgnoreNew
        $modeNote = if ($ShadowApply) {
            "shadow-apply (simulated ledger only)"
        } elseif ($DryRun) {
            "dry-run cycle"
        } else {
            "inspect (default, no cycle apply)"
        }
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "NomadQuant shadow daily worker: $modeNote — no broker orders" -Force
        Write-Host "Installed task '$TaskName' every 30 minutes. The script skips until the NY gate is due."
        Write-Host "Next NYSE 17:45 America/New_York: $($when.ny_local) (UTC $($when.utc))."
        Write-Host "Default mode is inspect unless you passed -ShadowApply. Disable: .\scripts\shadow-schedule.ps1 -Action disable"
    }
    "status" {
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List TaskName, State, Description
        Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List LastRunTime, LastTaskResult, NextRunTime
        $when = Get-NextNyWindow
        Write-Host "Next NYSE 17:45 America/New_York: $($when.ny_local) (UTC $($when.utc)). Host timezone is not the gate."
    }
    "disable" {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Disabled/removed task '$TaskName'."
    }
    "run-once" {
        if ($ShadowApply) { & $Script -ShadowApply }
        elseif ($DryRun) { & $Script -DryRun }
        else { & $Script }
    }
}
