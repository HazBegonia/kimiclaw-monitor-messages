# 内网页面字段监控

> 启动/停止/排障手册见 `docs/operations.md`；架构见 `AGENTS.md`「当前架构：py 通知器」节。

`src.intranet_filename_monitor` 由 Windows 常驻守护任务驱动，默认每 5 秒轮询一次。注册或更新守护任务：

```powershell
.\scripts\register-windows-scheduler.ps1 -IntervalSeconds 5
```

任务在当前人登录时启动 `scripts/run-intranet-monitor.ps1 -Mode Start`。任务计划程序的 `IgnoreNew` 设置和 Python 的 `state/monitor-resident.lock` 心跳锁共同避免重复实例。Python 子进程异常退出时，runner 会在锁失效后重启；runner 自身死亡由周期性守护触发器（默认 1 分钟，任务计划程序允许的最小间隔，`-GuardianMinutes` 可调）重新拉起，且 runner 致命异常会写入当日 scan 日志。

查看、手动启动、停止或删除守护任务：

```powershell
.\scripts\register-windows-scheduler.ps1 -Action List
.\scripts\register-windows-scheduler.ps1 -Action Run
.\scripts\register-windows-scheduler.ps1 -Action Stop
.\scripts\register-windows-scheduler.ps1 -Action Remove
```

监控目标为空时，常驻进程会安静空转，不产生错误日志或通知。`--once` 仍保留旧行为，空目标配置会报 `read_config` 错误，便于排障和回滚。

临时本地运行可以直接启动常驻模式：

```powershell
python -m src.intranet_filename_monitor --interval 5
```

版本选择配置位于 `config/intranet-versions.json`。例如：

```json
{
  "selectedVersions": [{ "id": "103300110002", "match": "103300110002" }]
}
```

每个选中版本在**文件集合发生变化时**才写入一条变化快照：`logs/intranet-focus/<version-id>/*.log`（首次基线也会写一条，此时改动前为空）。一条快照同时包含**改动前的全量文件清单**与**改动后的全量文件清单**（`before:` / `after:` 段）及增减计数；无变化的扫描不产生任何文件（2026-09-18 起生效，取代原先"每次扫描都写全量快照"的策略，消除了日志堆积）。

同时保留通用变化日志：首次成功请求只建立 `state/intranet-files.json` 基线；全局文件集合无变化时不写 `logs/intranet-diff/*.log`，发生新增或删除时才写入变化日志。版本列表为空时不生成版本快照，但通用变化监控仍然工作。

版本快照只记录文件名和元数据，不下载或解析 CSV 正文。因仅在变化时写入，流水量约等于 diff 日志量级；历史累积的 `logs/intranet-focus/` 旧文件（2026-09-11 至 2026-09-18 的"每次扫描全量"产物）可按需手工清理。

变化日志还可选 POST OpenClaw（历史：该事件唤醒/outbox 链路随 openclaw 于 2026-09-18 退役，`config/triage-message.txt` 已清空为 0 字节停用唤醒，代码休眠保留）：

```powershell
python -m src.intranet_filename_monitor --event-url http://127.0.0.1:3000/events --event-token SECRET
```

投递失败的事件保存在 `state/openclaw-pending/`（历史遗留，退役后不再产生新积压）。请求失败或异常页面保留旧状态，不误判删除。服务无 SSE/WebSocket/Webhook/ETag/Last-Modified，只能轮询准实时；页面约 1.33 MB，5 秒约 22.9 GiB/天，1 秒仅适合短测。本 change 不下载 CSV 正文；钉钉未接入。企业微信通知由 py 通知器 `src/intranet_notifier` 实现（见 `docs/workflow.md`「通知链路」；规则见 `config/triage-rules.json`）。

## 原始错误日志

Python 监控器遇到请求、页面校验、配置、状态或本地文件写入错误时，会将技术事实写入 `logs/intranet-error/YYYY-MM-DD.log`。文件采用 JSONL，每行一条记录，包含 `eventId`、`detectedAt`、`monitorId`、`mode`、`phase`、`errorType`、`message`、相关 `path`/脱敏 `url`、`statePreserved` 和 `retryable` 等字段。

错误日志只描述发生了什么，不判断业务重要性，不生成业务分析结论。重要性判定与企微推送由独立的 py 通知器完成：常驻任务 `KimiclawIntranetNotifier` 运行 `src/intranet_notifier`，每轮按 `config/triage-rules.json` 的确定性规则读取游标后的新记录、判定重要性、聚合为一条 markdown、经企微智能机器人 FF 长连接直推并推进 `state/notify-state.json` 游标；发送失败留痕于 `logs/intranet-notify/YYYY-MM-DD.log`（stage: wecom-send）且不推进游标、下轮自动重试。原基于 OpenClaw 事件唤醒会话/兜底 cron 的 triage 链路已于 2026-09-18 退役。

错误记录不会包含认证 Token、完整网页响应或 CSV 正文。默认保留 30 天、总大小上限 100 MB；清理失败不会覆盖原始错误处理结果。错误日志目录不可写时，程序会将脱敏摘要回退输出到 stderr。
