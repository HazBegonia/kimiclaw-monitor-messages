# Proposal

## Why

上级通过在企微群 @FF 提需求来调整监控行为，但当前链路存在两个断点：

1. **需求闭环断裂**：Claw 收到需求后没有任何受约束的修改协议——没有白名单边界、没有确认闸、没有写后校验、没有失败回滚、没有留痕。名义上已退役的 `skills/intranet-message-triage/SKILL.md` 仍被 `skills.load.extraDirs` 加载，旧草案机制半活着，规则过时且无人维护。
2. **config 与 src 之间存在「假配置」**：`config/triage-rules.json` 的 `suppress.filenamePatterns`、`push.errors.consecutiveFetchFailures`、`semantic` 三个字段通过校验但不被执行。Claw 按需求改这些字段会「校验通过、回复成功、行为不变」，静默失效。

## What Changes

- 新建 skill `skills/ff-config-assistant/SKILL.md`：定义 @FF 会话的完整行为——自然语言需求理解、只读查询直接回答、变更请求走「草案 → 群内回显改前/改后 → 『写入』确认 → 落盘 → 写后校验 → 失败自动回滚 → 留痕」协议，「放弃」作废草案；同时只有一个待写入草案。
- 白名单制：仅允许对话修改 `config/intranet-versions.json`（关注版本）、`config/monitors.json`（监控目标）、`config/triage-rules.json`（推送规则条目级）、`config/notifier.json`（chatid）。白名单外（代码、密钥、systemd unit、轮询间隔）一律拒绝并说明原因。
- skill 内置「能力表」：每类需求 → 改哪个 config 键 → 用哪条校验命令验证；表外需求回复「要改代码/人工处理」。
- **修复假配置（triage-rules.json）**：
  - 激活 `suppress.filenamePatterns`：命中 fnmatch 模式的文件名从 diff 的 added/removed 中剔除后再判定重要性；
  - 删除 `semantic` 与 `push.errors.consecutiveFetchFailures` 两个占位字段（config、校验器、文档同步移除；语义等上级定义后再加回并激活）。
- 将已退役的 `skills/intranet-message-triage/SKILL.md` 移出 `skills/`（存档至 `wiki/`），Claw 不再加载旧规则；`state/requirements.json` 需求台账废弃（草案文件 `state/chat-drafts.json` 兼任审计台账）。
- config 全部热读生效，无需重启任何服务。

## Capabilities

### New Capabilities

- `ff-config-assistant`: @FF 企微会话中的对话式配置修改能力——需求理解、草案确认闸、白名单边界、写后校验与自动回滚、留痕、只读查询。

### Modified Capabilities

- `py-notifier-loop`: 重要性判定规则新增「filenamePatterns 命中的文件名在判定前剔除」行为；规则文件移除 `semantic` 与 `consecutiveFetchFailures` 占位字段（校验器对未知字段改为显式拒绝，杜绝新增假配置）。

## Impact

- **新增**：`skills/ff-config-assistant/SKILL.md`。
- **修改**：`src/triage_rules.py`（filenamePatterns 生效、占位字段移除、未知字段拒绝）、`config/triage-rules.json`（删占位字段）、`tests/test_triage_rules.py`。
- **移动**：`skills/intranet-message-triage/SKILL.md` → `wiki/`（历史存档，不再被加载）。
- **废弃**：`state/requirements.json`（台账职能由 `state/chat-drafts.json` 兼任）。
- **不影响**：采集器 `src/intranet_filename_monitor.py`、推送链路 `src/bot_tool.py` / `src/wecom_bot_client.py`、systemd unit、轮询间隔（维持人工）。
- **明确排除**：`monitors.json` 的 `profile.extension` 硬编码问题（陷阱 1）与文件内容变化监控，本 change 不处理。
