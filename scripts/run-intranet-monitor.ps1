[CmdletBinding()]
param(
    [ValidateSet('Start', 'Once')]
    [string]$Mode = 'Start',
    [double]$Interval = 5,
    [double]$Timeout = 10,
    [string]$EventUrl = '',
    [string]$EventToken = ''
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$argsList = @('-m', 'src.intranet_filename_monitor', '--interval', $Interval, '--timeout', $Timeout)
if ($EventUrl) { $argsList += @('--event-url', $EventUrl) }
if ($EventToken) { $argsList += @('--event-token', $EventToken) }
if ($Mode -eq 'Once') { $argsList += '--once' }
Push-Location $workspace
try { & python @argsList; exit $LASTEXITCODE }
finally { Pop-Location }
