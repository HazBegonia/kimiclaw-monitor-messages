[CmdletBinding()]
param(
    # Accepted for register-windows-scheduler.ps1 compatibility; unused.
    [double]$Interval = 5,
    [ValidateRange(1, 300)]
    [int]$RestartDelaySeconds = 5
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $workspace 'logs\openclaw-gateway'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir ((Get-Date).ToString('yyyy-MM-dd') + '.log')
Add-Content -LiteralPath $logFile -Value ("=== run start " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " ===")
Push-Location $workspace
try {
    # Resolve the .cmd shim explicitly: CreateProcess does not try PATHEXT.
    $openclaw = (Get-Command 'openclaw.cmd' -ErrorAction SilentlyContinue).Source
    if (-not $openclaw) { $openclaw = (Get-Command 'openclaw.exe' -ErrorAction SilentlyContinue).Source }
    if (-not $openclaw) { throw 'openclaw CLI not found on PATH' }
    do {
        # PS 5.1 turns any native stderr line into a terminating NativeCommandError
        # under -ErrorActionPreference Stop; relax it around the native call.
        $ErrorActionPreference = 'Continue'
        & $openclaw 'gateway' 'run' *>> $logFile
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        Add-Content -LiteralPath $logFile -Value ("=== run end " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " exit=$code ===")
        Add-Content -LiteralPath $logFile -Value ("=== resident restart " + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') + " after=$RestartDelaySeconds seconds ===")
        Start-Sleep -Seconds $RestartDelaySeconds
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
