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

function Get-NextWeekday1745EasternLocal {
    # Target: next Mon–Fri 17:45 America/New_York, converted to local time for Task Scheduler.
    $easternId = "Eastern Standard Time"
    $eastern = [TimeZoneInfo]::FindSystemTimeZoneById($easternId)
    $utcNow = [DateTime]::UtcNow
    $etNow = [TimeZoneInfo]::ConvertTimeFromUtc($utcNow, $eastern)

    $candidate = $etNow.Date.AddHours(17).AddMinutes(45)
    if ($etNow -ge $candidate) {
        $candidate = $candidate.AddDays(1)
    }
    while ($candidate.DayOfWeek -eq [DayOfWeek]::Saturday -or $candidate.DayOfWeek -eq [DayOfWeek]::Sunday) {
        $candidate = $candidate.AddDays(1)
    }

    $local = [TimeZoneInfo]::ConvertTime($candidate, $eastern, [TimeZoneInfo]::Local)
    return @{
        EasternAt   = $candidate
        LocalAt     = $local
        LocalTime   = $local.TimeOfDay
    }
}

switch ($Action) {
    "install" {
        $when = Get-NextWeekday1745EasternLocal
        $dailyArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
        if ($ShadowApply) { $dailyArgs += " -ShadowApply" }
        elseif ($DryRun) { $dailyArgs += " -DryRun" }
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $dailyArgs
        $atLocal = $when.LocalAt.ToString("HH:mm")
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $atLocal
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
        Write-Host "Installed task '$TaskName' at local $atLocal (maps to next 17:45 America/New_York ≈ $($when.EasternAt.ToString('yyyy-MM-dd HH:mm')) ET)."
        Write-Host "Default mode is inspect unless you passed -ShadowApply. Disable: .\scripts\shadow-schedule.ps1 -Action disable"
    }
    "status" {
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List TaskName, State, Description
        Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List LastRunTime, LastTaskResult, NextRunTime
        $when = Get-NextWeekday1745EasternLocal
        Write-Host "Next 17:45 ET → local $($when.LocalAt.ToString('yyyy-MM-dd HH:mm')) ($($when.LocalTime))"
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
