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

# 可选：triage+推送 agent 任务（flow1/flow2 末端）。配置含 notifyJobName/notifyEvery 时注册。
$notifyJobName = [string]$config.notifyJobName
$notifyEvery = [string]$config.notifyEvery
if ($notifyJobName -and $notifyEvery) {
    $notifyMessage = @'
【内网监控 triage 轮次】项目根目录为 C:/Users/ELadmin/Desktop/program/kimiclaw-monitor-messages，下面所有相对路径都基于它。先完整阅读 .agents/skills/intranet-message-triage/SKILL.md 并严格按该 skill 执行一轮：只处理 state/notify-state.json 游标之后的 logs/intranet-diff/ 与 logs/intranet-error/ 新增产物；按 skill 规则判定重要性；有重要内容则按 skill 模板聚合成一条 markdown，通过 wecom-cli tool 发送（先 message aibot sessions list，按群名「未命名企业」精确匹配 group 会话取当次 chat_id，再 message aibot send）；发送成功才推进 state/notify-state.json 游标；发送失败写 logs/intranet-notify/ 当日 .log 并保留游标；无重要内容则不发送任何消息、直接结束。不要改动项目根目录以外的任何文件。
'@
    & openclaw cron add `
        --name $notifyJobName `
        --agent main `
        --every $notifyEvery `
        --message $notifyMessage `
        --declaration-key $notifyJobName `
        --no-deliver `
        --json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "OpenClaw cron 注册失败（$notifyJobName），退出码：$LASTEXITCODE"
    }
    Write-Host "已注册 OpenClaw cron：$notifyJobName（每 $notifyEvery 触发 agent 执行 triage+企微推送）。"
}
Write-Host "查看：.\scripts\register-openclaw-intranet-cron.ps1 -Action List"
Write-Host "删除：先查看任务 ID，再运行 -Action Remove -JobId <id>"
