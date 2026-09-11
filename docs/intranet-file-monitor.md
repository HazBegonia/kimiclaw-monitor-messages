# 内网页面字段监控

`src.intranet_filename_monitor` 支持常驻轮询，也支持由 OpenClaw cron 定期调用 `--once` 完成单次扫描。若只想启动一个 OpenClaw，使用项目脚本注册分钟级 cron：

```powershell
.\scripts\register-openclaw-intranet-cron.ps1
```

该任务每轮调用 `scripts/run-intranet-monitor.ps1 -Mode Once`，因此不会叠加多个常驻 Python 进程。调度频率和 Python 的扫描参数配置在 `config/openclaw-intranet-cron.json`，查看或删除任务：

```powershell
.\scripts\register-openclaw-intranet-cron.ps1 -Action List
.\scripts\register-openclaw-intranet-cron.ps1 -Action Remove -JobId <任务ID>
```

需要约 5 秒准实时性时，仍应直接运行常驻模式：

```powershell
python -m src.intranet_filename_monitor --interval 5
```

版本选择配置位于 `config/intranet-versions.json`。例如：

```json
{
  "selectedVersions": [
    { "id": "103300110002", "match": "103300110002" }
  ]
}
```

每次成功扫描都会为每个选中版本写入全量快照：
`logs/intranet-focus/<version-id>/*.log`。快照包含该版本当前所有匹配的 CSV 文件名，即使本轮没有变化。

同时保留通用变化日志：首次成功请求只建立 `state/intranet-files.json` 基线；全局文件集合无变化时不写 `logs/intranet-diff/*.log`，发生新增或删除时才写入变化日志。版本列表为空时不生成版本快照，但通用变化监控仍然工作。

版本快照只记录文件名和元数据，不下载或解析 CSV 正文。每次扫描都会产生快照文件，请根据磁盘容量维护日志保留策略。

变化日志还可选 POST OpenClaw：

```powershell
python -m src.intranet_filename_monitor --event-url http://127.0.0.1:3000/events --event-token SECRET
```

投递失败的事件保存在 `state/openclaw-pending/`。请求失败或异常页面保留旧状态，不误判删除。服务无 SSE/WebSocket/Webhook/ETag/Last-Modified，只能轮询准实时；页面约 1.33 MB，5 秒约 22.9 GiB/天，1 秒仅适合短测。本 change 不下载 CSV 正文；钉钉未接入。企业微信通知已由 `wecom-aibot-notify` 实现（见 `docs/workflow.md`「通知链路」）。

## 原始错误日志

Python 监控器遇到请求、页面校验、配置、状态或本地文件写入错误时，会将技术事实写入 `logs/intranet-error/YYYY-MM-DD.log`。文件采用 JSONL，每行一条记录，包含 `eventId`、`detectedAt`、`monitorId`、`mode`、`phase`、`errorType`、`message`、相关 `path`/脱敏 `url`、`statePreserved` 和 `retryable` 等字段。

错误日志只描述发生了什么，不判断业务重要性，不生成业务分析结论。重要性判定与企微推送由 `intranet-message-notify` cron agent 任务按 `.agents/skills/intranet-message-triage/SKILL.md` 完成（读取游标后的新记录、判定、聚合推送、推进游标）。

错误记录不会包含认证 Token、完整网页响应或 CSV 正文。默认保留 30 天、总大小上限 100 MB；清理失败不会覆盖原始错误处理结果。错误日志目录不可写时，程序会将脱敏摘要回退输出到 stderr。
