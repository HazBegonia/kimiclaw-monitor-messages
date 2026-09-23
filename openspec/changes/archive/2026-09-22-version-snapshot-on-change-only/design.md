## Context

版本快照当前实现：`run_once` 在每个成功扫描轮次里对每个选中版本无条件调用 `write_snapshot_log`（全量清单、无变化也写），导致每 5–7 秒一份文件。采集任务由 `KimiclawIntranetResident` 常驻驱动，约每 5 秒一轮。变更动机见 proposal.md；对其的要求（仅变化时写、含改前/改后双全量）见 specs delta。

约束：错误日志 phase 名 `write_snapshot_log` 是规则引擎 `phases` 键，不得改名；采集器常驻进程需重启才加载新代码；状态文件由旧代码写入、无 `versionFiles` 字段，需无痛迁移。

## Goals / Non-Goals

**Goals:**

- 版本快照仅在文件集合变化（或首次基线）时写，无变化零文件，杜绝 ~12 份/分钟的堆积。
- 每条变化日志天然可审计：改前全量 + 改后全量 + 计数，无需回查其他文件即可还原任意一次变化的来龙去脉。

**Non-Goals:**

- 不改通知器、规则引擎、计划任务、游标、凭证（快照日志当前无消费者）。
- 不清理历史旧格式快照文件（人工决定）。
- 不引入按时间保留/容量上限的新策略（变化即写已使流水量与 diff 同量级）。

## Decisions

**1. 版本上次集合记在哪里 → 监视器状态文件的 `versionFiles` 字段。**

- 方案 A：状态文件加 `versionFiles: {version_id: [sorted files]}`（采用）。与 root 快照同文件、同原子写，天然随指纹一起回滚；每监视器独立。
- 方案 B：从该版本最新一份快照日志反推上次集合（解析 before/after）。省状态字段但要读历史文件、与"无变化不写"自相矛盾（无变化时根本没有新日志可读）。
- 方案 C：独立 per-version 状态文件。文件数膨胀，违背简化意图。

**2. 变化判定 → 排序后集合比较（`sorted(before) != sorted(after)`），复用 `diff_filenames` 计算增减。**

**3. 日志格式 → 沿用文本行格式（`monitorId:`/`detectedAt:` 等），新增 `changed/addedCount/removedCount/beforeCount/afterCount` 头字段与 `before:`/`after:` 两个清单段**（替换旧的 `count:`/`files:`）。保持文件命名 `_next_log_path`（时间戳）不变，且保留通用 diff 日志格式完全不变。

**4. phase 保持 `write_snapshot_log`**：写快照失败仍记该 phase，规则引擎既有 phases 配置不感知。

**5. 旧状态迁移**：`version_files = prev.get("versionFiles", {})`——旧文件无此键 → 首轮视为全版本基线（before 为空），每个版本补写一条基线日志后自动收敛为"仅变化时写"。

## Risks / Trade-offs

- [迁移瞬间每版本补写一条"改动前为空"的基线日志] → 一次性、量级与变化日志相同，属预期行为并在 specs 的 Initial baseline 场景中表达。
- [状态写入失败/进程被杀在"写变化日志后、写状态前"的窗口 → 下轮重复写同一条变化日志] → 与通用 diff 日志相同的 at-least-once 语义，审计可接受（重复条目时间戳不同、内容一致）。
- [无变化时段不再有连续留痕，无法事后证明某时段集合稳定] → 用户明确选择该取舍（与 diff 日志一致）；需要"每轮留痕"时可另行加保留策略。
- [采集任务升级需重启进程才生效] → 走既有任务 Stop→Run 流程（runner/守护触发器会在崩溃时自动拉起新代码，无需手动干预）。

## Migration Plan

1. 代码 + 测试改动（已完成，78 测试全绿）。
2. 重启 `KimiclawIntranetResident`（Stop → kill 旧 python → Run）。
3. 验证：重启后首个变化（或基线）日志为 `before:`/`after:` 新格式；22 秒观察期内 focus 文件数不变。
4. 回滚：仅需还原 `src/intranet_filename_monitor.py` 至旧实现并重启任务；状态文件多出的 `versionFiles` 字段对旧代码无害（旧代码直接忽略未知键）。

## Open Questions

无（变化已实现并在生产验证；后续如用户决定清理历史旧格式快照，属运维操作，不进 specs）。