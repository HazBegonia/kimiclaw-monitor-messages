# 内网页面字段监控(采集器)

> 运维启停见 `operations.md`;整体架构见 `architecture.md`。

采集器为 `src/intranet_filename_monitor`,由 `kimiclaw-monitor.service` 常驻驱动(`--interval 10 --timeout 10`)。单实例由 `state/monitor-resident.lock` 心跳锁保证(活锁安静退出、陈旧可接管)。

## 监控目标:config/monitors.json

目标在 `config/monitors.json`,可配多个,每目标独立 state(`state/intranet-files-<id>.json`):

```json
{
  "targets": [
    {
      "id": "intranet-root",
      "url": "http://172.16.30.20:8011/",
      "profile": { "root_files": { "type": "link_set", "extension": ".csv" } }
    }
  ]
}
```

监控目标为空时,常驻进程安静空转,不产生错误日志或通知;`--once` 则报 `read_config` 错误,便于排障。

## 产物:diff、版本快照、错误日志

**通用变化日志** `logs/intranet-diff/`:首次成功请求只建立基线;文件集合无变化不写文件,发生新增/删除时才写变化日志。请求失败或异常页面保留旧状态,不误判删除。

**版本快照** `logs/intranet-focus/<version-id>/`:版本选择配置在 `config/intranet-versions.json`,例如:

```json
{ "selectedVersions": [{ "id": "103300110002", "match": "103300110002" }] }
```

每个选中版本在**文件集合发生变化时**才写一条快照(首次基线也写一条,改动前为空),内含改动前/改动后两份全量文件清单(`before:` / `after:` 段)及增减计数;无变化不产生文件(2026-09-18 起策略,取代每轮全量留痕)。快照只记录文件名和元数据,不下载或解析 CSV 正文。版本列表为空时停用快照,通用变化监控仍工作。2026-09-11 至 09-18 的历史全量快照可按需手工清理。

**原始错误日志** `logs/intranet-error/YYYY-MM-DD.log`:JSONL,每行一条,含 `eventId`、`detectedAt`、`monitorId`、`mode`、`phase`、`errorType`、`message`、脱敏 `url`、`statePreserved`、`retryable` 等字段。只记录技术事实,不做业务重要性判断(判定与推送由通知器完成)。错误记录不含认证 Token、完整网页响应或 CSV 正文;默认保留 30 天、总大小上限 100 MB;清理失败不影响原始错误处理;目录不可写时降级输出脱敏摘要到 stderr。

## 手动运行

```bash
python -m src.intranet_filename_monitor --interval 10 --timeout 10   # 常驻
python -m src.intranet_filename_monitor --once                       # 单轮
```

主要参数:`--url`(覆盖目标)、`--interval`、`--timeout`、`--state`、`--log-dir`、`--focus-log-dir`、`--error-log-dir`、`--versions-config`、`--monitors-config`。`--event-url` / `--event-token` / `--outbox` 是已退役的 OpenClaw 事件唤醒链路的休眠代码,不使用(`config/triage-message.txt` 已清空为 0 字节)。

## 限制:只能轮询,准实时

- 目标服务无 SSE/WebSocket/Webhook/ETag/Last-Modified,只能轮询准实时。
- 页面约 1.33 MB:10 秒间隔约 11.5 GiB/天,5 秒约 22.9 GiB/天,1 秒仅适合短测。
- 钉钉未接入;企业微信通知由通知器 `src/intranet_notifier` 实现(规则见 `config/triage-rules.json`)。
