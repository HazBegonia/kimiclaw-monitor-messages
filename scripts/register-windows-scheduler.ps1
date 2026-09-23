[CmdletBinding()]
param(
    [ValidateSet('Register', 'List', 'Remove', 'Run', 'Stop')]
    [string]$Action = 'Register',
    [string]$TaskName = 'KimiclawIntranetResident',
    [string]$EntryScript = 'run-intranet-monitor.ps1',
    [ValidateRange(2, 3600)]
    [int]$IntervalSeconds = 5,
    [ValidateRange(1, 60)]
    [int]$GuardianMinutes = 1
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $workspace ("scripts\" + $EntryScript)
$isMonitorRunner = $EntryScript -like '*monitor*'
$taskUser = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }

function Show-Task {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Scheduled task not found: $TaskName"
        return
    }

    $task | Select-Object TaskName, State, TaskPath | Format-List
    Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns
}

switch ($Action) {
    'List' { Show-Task; exit 0 }
    'Remove' {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed scheduled task: $TaskName"
        exit 0
    }
    'Run' {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Started scheduled task: $TaskName"
        exit 0
    }
    'Stop' {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "Stopped scheduled task: $TaskName"
        exit 0
    }
}

# Resident runners take -Interval N; the monitor runner additionally takes
# -Mode Start (notifier runner is always resident, no Mode parameter).
if ($isMonitorRunner) {
    $runnerArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Mode Start -Interval {1}' -f $runner, $IntervalSeconds
}
else {
    $runnerArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Interval {1}' -f $runner, $IntervalSeconds
}
# conhost --headless detaches its child process, preventing Task Scheduler from
# observing crashes. Keep PowerShell as the action process and hide it through
# both its window style and the task setting so restart-on-failure remains valid.
$taskAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $runnerArguments -WorkingDirectory $workspace
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
# RestartOnFailure alone proved unreliable for runner-level deaths (no retry fired
# after the runner process died, 2026-09-18 incident). A periodic guardian trigger
# is the fallback: IgnoreNew makes repeats a no-op while the task is running,
# and starts it within $GuardianMinutes when it is dead.
$guardianTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $GuardianMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -Hidden -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger @($trigger, $guardianTrigger) -Settings $settings -Principal $principal -Description "Resident intranet task ($EntryScript); polls every $IntervalSeconds seconds; guardian trigger refires every $GuardianMinutes minutes." -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName (logon trigger + $GuardianMinutes min guardian trigger, resident mode, $IntervalSeconds second interval)"
Write-Host "Check:  .\scripts\register-windows-scheduler.ps1 -Action List -TaskName $TaskName"
Write-Host "Manual run: .\scripts\register-windows-scheduler.ps1 -Action Run -TaskName $TaskName"
Write-Host "Stop:   .\scripts\register-windows-scheduler.ps1 -Action Stop -TaskName $TaskName"