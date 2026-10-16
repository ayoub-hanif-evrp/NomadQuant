# Opt-in Windows Task Scheduler helper for NomadQuant shadow daily checks.
# NEVER schedules broker orders. Does NOT auto-install; call install explicitly.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("install", "status", "disable", "run-once")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$TaskName = "NomadQuantShadowDaily"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $PSScriptRoot "shadow-daily.ps1"

switch ($Action) {
    "install" {
        # Weekdays 17:45 America/New_York-ish local: user must confirm local TZ.
        # Task uses local machine time; document DST: prefer 17:45 Eastern mapped to local.
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 5:45PM
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "NomadQuant forward shadow dry-run (no broker orders)" -Force
        Write-Host "Installed task '$TaskName'. Disable with: .\scripts\shadow-schedule.ps1 -Action disable"
    }
    "status" {
        Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List TaskName, State
        Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue |
            Format-List LastRunTime, LastTaskResult, NextRunTime
    }
    "disable" {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Disabled/removed task '$TaskName'."
    }
    "run-once" {
        & $Script
    }
}
