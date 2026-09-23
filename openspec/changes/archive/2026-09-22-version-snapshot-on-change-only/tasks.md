> 注：本 change 为**实施后补记**——代码、测试、部署与验证已于 2026-09-18 完成并上线，tasks 全部按实际完成状态勾选。

## 1. 采集器实现（src/intranet_filename_monitor.py）

- [x] 1.1 将 `write_snapshot_log` 替换为 `write_version_change_log`：一条日志含 `changed/addedCount/removedCount/beforeCount/afterCount` 头字段与 `before:`（改动前全量）、`after:`（改动后全量）两个清单段
- [x] 1.2 `_write_state` 增加 `versionFiles` 字段持久化（每版本最近一次匹配集合）；旧状态文件无该键时按空处理（自动迁移）
- [x] 1.3 `run_once` 版本分支改为：对比状态 `versionFiles`，集合变化（含首次基线）才写一条变化日志并更新记录；无变化零文件；phase 保持 `write_snapshot_log` 不变

## 2. 测试（tests/）

- [x] 2.1 原 `test_selected_version_writes_snapshot_on_unchanged_scans` 改为 `test_version_snapshot_written_only_on_change_with_before_after`：两次未变化扫描只产 1 份基线；真实变化时产 1 条并断言 `before:`/`after:` 双全量与计数
- [x] 2.2 全套测试通过：`python -m pytest tests/ -q` → 78 passed（含既有采集器用例零回归）

## 3. 部署与验证

- [x] 3.1 更新 `AGENTS.md`（链路描述注明快照策略变更）与 `docs/intranet-file-monitor.md`（快照段落重写：仅变化时写、含改前/改后全量；历史产物按需人工清理）
- [x] 3.2 重启 `KimiclawIntranetResident` 任务加载新代码：验证重启后写入新格式基线日志（beforeCount=0/afterCount=458），并确认 22 秒观察期内 focus 文件数保持不变（堆积停止）