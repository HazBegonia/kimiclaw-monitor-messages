[CmdletBinding()]
param(
    [ValidateSet('Start', 'Once')]
    [string]$Mode = 'Start',
    [double]$Interval = 5,
    [double]$Timeout = 10,
    [ValidateRange(1, 300)]
    [int]$RestartDelaySeconds = 5
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$argsList = @('-m', 'src.intranet_filename_monitor', '--interval', $Interval, '--timeout', $Timeout)
$effectiveRestartDelaySeconds = [Math]::Max($RestartDelaySeconds, [int][Math]::Floor($Interval * 2) + 1)
if ($Mode -eq 'Once') { $argsList += '--once' }
$logDir = Join-Path $workspace 'logs\intranet-scan'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir ((Get-Date).ToString('yyyy-MM-dd') + '.log')
Add-Content -LiteralPath $logFile -Value ("=== run start " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " mode=$Mode ===")
Push-Location $workspace
try {
    # PS 5.1 turns any native stderr line into a terminating NativeCommandError
    # under -ErrorActionPreference Stop; relax it around the python call.
    do {
        $ErrorActionPreference = 'Continue'
        & python @argsList *>> $logFile
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        Add-Content -LiteralPath $logFile -Value ("=== run end " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " exit=$code ===")
        if ($Mode -eq 'Once' -or $code -eq 0) {
            exit $code
        }
        Add-Content -LiteralPath $logFile -Value ("=== resident restart " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " after=$effectiveRestartDelaySeconds seconds ===")
        Start-Sleep -Seconds $effectiveRestartDelaySeconds
    } while ($true)
}
catch {
    # Runner-level fatal errors must leave a trace: Task Scheduler only records
    # the exit code, and the Operational event log may be disabled.
    try {
        Add-Content -LiteralPath $logFile -Value ("=== runner fatal " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " " + (($_ | Out-String).Trim() -replace "`r?`n", ' | ') + " ===")
    } catch {}
    exit 1
}
finally { Pop-Location }
