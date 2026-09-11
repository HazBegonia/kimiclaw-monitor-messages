# 单一 OpenClaw 入口（内网 Web 最小尝试）

只需启动一个 OpenClaw gateway。由 OpenClaw cron 按配置文件中的间隔调用 Python **单次扫描**，不再另行启动 Windows 任务计划或 Python 常驻进程；扫描产物由另一个 cron agent 任务做重要性判定并推送企业微信（见下文「通知链路」）。

调度配置在 `config/openclaw-intranet-cron.json`，修改 `every` 即可调整 OpenClaw 调用频率；`scanIntervalSeconds` 和 `timeoutSeconds` 控制 Python 参数；`notifyJobName` 和 `notifyEvery` 控制 triage+推送任务（置空则不注册该任务）。

项目内 PowerShell 脚本已统一保存为 **UTF-8 with BOM**，兼容 Windows PowerShell 5.1。若用编辑器重新保存脚本，请保持该编码格式。

```powershell
# 在项目根目录执行；频率读取 config/openclaw-intranet-cron.json
.\scripts\register-openclaw-intranet-cron.ps1

# 查看已注册任务（包含禁用任务）
.\scripts\register-openclaw-intranet-cron.ps1 -Action List
```

任务实际执行的命令等价于：

```powershell
.\scripts\run-intranet-monitor.ps1 -Mode Once -Interval 5 -Timeout 10
```

Python 默认读取 `config/intranet-versions.json`。该文件中的 `selectedVersions` 决定哪些版本生成全量快照；例如将 `103300110002` 替换或追加为公司实际选择的版本。快照写入 `logs/intranet-focus/<version-id>/`，通用新增/删除变化仍写入 `logs/intranet-diff/`。

Python 发现扫描或本地持久化错误时，将原始技术错误写入 `logs/intranet-error/YYYY-MM-DD.log`（JSONL）。记录包含错误阶段、异常类型、脱敏上下文、`eventId` 和最近一次成功状态是否保留。当前阶段只生成原始错误日志，不做业务重要性判断、不生成分析日志、不发送企业微信或其他通知；后续再由 Claw skill 读取这些记录。

脚本使用固定 `declaration-key`，重复注册同名任务可复用同一声明。删除时先执行 `-Action List`，再按返回的任务 ID：

```powershell
.\scripts\register-openclaw-intranet-cron.ps1 -Action Remove -JobId <任务ID>
```

OpenClaw cron 的调度粒度适合分钟级（例如 `-Every 1m`、`-Every 5m`），不适合 5 秒级实时监控。若必须约 5 秒轮询，请改用 `python -m src.intranet_filename_monitor --interval 5` 常驻模式（并接受需要单独守护该进程）。

## 通知链路（flow1/flow2 末端）

扫描只写本地日志；通知由 cron agent 任务 `intranet-message-notify`（与扫描任务同脚本注册）完成：每轮阅读 `.agents/skills/intranet-message-triage/SKILL.md`，处理 `state/notify-state.json` 游标之后的新产物，重要消息聚合为一条 markdown，经企业微信智能机器人 FF（`@wecom/wecom-openclaw-plugin`，长连接）推送到「未命名企业」全员群。

前提与排障：

- 机器人凭证在全局 `~/.openclaw/openclaw.json`（`channels.wecom.*`），本仓库不落密钥；目标群信息在 `config/wecom-aibot.json`。
- 企微限制：目标会话须先有人 @FF 发过消息，机器人才能主动推送。若群会话失效（如机器人被移出群再加回），重新 @FF 发一条消息并核对 `config/wecom-aibot.json` 中的 chatId。
- 推送失败不丢消息：失败写入 `logs/intranet-notify/YYYY-MM-DD.log`，游标不推进，下轮重发。
- 重要性判定规则在 `intranet-message-triage` skill 中，调整规则即调整推送行为。
