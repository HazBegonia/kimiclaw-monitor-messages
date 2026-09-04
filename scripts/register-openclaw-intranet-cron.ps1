[CmdletBinding()]
param(
    [ValidateSet('Register', 'List', 'Remove')]
    [string]$Action = 'Register',
    [string]$JobName = '',
    [string]$Every = '',
    [double]$Interval = 0,
    [double]$Timeout = 0,
    [string]$JobId
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $workspace 'config\openclaw-intranet-cron.json'

if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    throw '未找到 openclaw CLI。请先安装并确保 openclaw 在 PATH 中。'
}

switch ($Action) {
    'List' {
        & openclaw cron list --all
        exit $LASTEXITCODE
    }
    'Remove' {
        if (-not $JobId) {
            throw 'Remove 操作需要 -JobId；先运行 -Action List 查看任务 ID。'
        }
        & openclaw cron rm $JobId
        exit $LASTEXITCODE
    }
}

$config = if (Test-Path -LiteralPath $configPath) {
    Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
} else {
    throw "缺少配置文件：$configPath"
}
if (-not $JobName) { $JobName = [string]$config.jobName }
if (-not $Every) { $Every = [string]$config.every }
if ($Interval -le 0) { $Interval = [double]$config.scanIntervalSeconds }
if ($Timeout -le 0) { $Timeout = [double]$config.timeoutSeconds }
if (-not $JobName -or -not $Every -or $Interval -le 0 -or $Timeout -le 0) {
    throw "配置无效：$configPath 需要 jobName、every、scanIntervalSeconds、timeoutSeconds"
}
$runner = Join-Path $workspace 'scripts\run-intranet-monitor.ps1'
$commandArgv = @(
    'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', $runner, '-Mode', 'Once', '-Interval', ([string]$Interval), '-Timeout', ([string]$Timeout)
) | ConvertTo-Json -Compress
# Windows PowerShell 5.1 strips embedded quotes from native command arguments;
# escape them so OpenClaw receives a valid JSON array.
$commandArgv = $commandArgv.Replace('"', '\"')

# declaration-key 使重复执行 Register 保持幂等（由 OpenClaw 更新/复用同一声明）。
& openclaw cron add `
    --name $JobName `
    --every $Every `
    --command-argv $commandArgv `
    --command-cwd $workspace `
    --declaration-key $JobName `
    --no-deliver `
    --no-output-timeout-seconds ([math]::Ceiling($Timeout + 5)) `
    --json
if ($LASTEXITCODE -ne 0) {
    throw "OpenClaw cron 注册失败，退出码：$LASTEXITCODE"
}

Write-Host "已注册 OpenClaw cron：$JobName（每 $Every 调用 run-intranet-monitor.ps1 -Mode Once）。"
Write-Host "查看：.\scripts\register-openclaw-intranet-cron.ps1 -Action List"
Write-Host "删除：先查看任务 ID，再运行 -Action Remove -JobId <id>"
