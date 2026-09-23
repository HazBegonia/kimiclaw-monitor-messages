## Why

采集器此前**每次成功扫描（约每 5–7 秒一轮）都为每个选中版本写一份全量快照日志**，即使文件集合没有任何变化。按当前运行节奏约每分钟 12 份、每天 ~720 份（~12-13 MB/天，年化约 4.5 GB 且文件数爆炸式增长），日志目录持续堆积、接近失控。2026-09-18 用户明确要求：快照只在变化时写，且每条记录必须同时包含**改动前全量清单**与**改动后全量清单**。

## What Changes

- 采集器将按版本的「全量快照留痕」改为「仅变化时写一条变化快照」：
  - 某版本文件集合相较上次记录**无变化** → 本轮**不产生任何文件**（与通用 diff 日志同一节奏）。
  - 某版本文件集合**发生变化**（含首次基线，此时改动前为空）→ 写一条 `logs/intranet-focus/<version-id>/<ts>.log`，内容包含 `changed: true`、`addedCount`、`removedCount`、`beforeCount`、`afterCount`，以及 `before:`（改动前全部文件名）与 `after:`（改动后全部文件名）两个完整清单段。
- 监视器状态文件（`state/intranet-files-<id>.json`）新增 `versionFiles` 字段，记录每个版本最近一次成功扫描的匹配集合；旧状态文件无该字段时自动迁移——升级后首轮为每个版本补写一条「改动前为空」的基线日志，之后恢复正常。
- 错误日志 phase 名 `write_snapshot_log` **保持不变**（规则引擎的 phases 键依赖它，不产生规则语义变化）。
- 文档同步更新（`AGENTS.md`、`docs/intranet-file-monitor.md`）。
- 历史遗留的旧格式快照文件（2026-09-11 至 2026-09-18 的"每次扫描全量"产物）不在本 change 处理范围内，可按需手工清理。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `configurable-version-snapshot-logs`：需求「Full snapshot for selected versions」从"每次成功扫描为每个选中版本生成全量快照日志（即使无变化）"改为"仅当版本文件集合变化（或首次基线）时生成一条快照日志，日志须包含改动前与改动后两份完整文件清单及增减计数；无变化不生成文件"。

## Impact

- `src/intranet_filename_monitor.py`：`write_snapshot_log` 替换为 `write_version_change_log`（before/after 双清单）；`run_once` 版本快照分支改为对比状态中的 `versionFiles` 后决定是否写入；`_write_state` 增加 `versionFiles` 持久化。
- `tests/test_intranet_filename_monitor.py`：原「未变化也写快照」用例改为「仅变化时写、且含前后双全量」断言。
- 文档：`AGENTS.md`（链路描述）、`docs/intranet-file-monitor.md`（快照段重写）。
- 运行影响：通知器、规则引擎、计划任务、凭证、游标均不受影响（快照日志本就没有被任何消费者读取）；采集任务需重启以加载新代码。