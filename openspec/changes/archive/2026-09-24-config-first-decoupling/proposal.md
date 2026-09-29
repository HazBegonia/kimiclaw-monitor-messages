# Proposal

## Why

上级通过群内 @FF 提监控需求变更，Claw 按 ff-config-assistant 协议只改 `config/` 落盘生效。但当前部分高频需求的语义仍硬编码在 `src/` 里：diff 推送只有「排除哪些文件」（suppress）没有「只关注哪些文件」（include）；版本匹配的语义写死为子串包含。这类需求一来就必须改 Python 代码，违背「config 优先、尽量少动 src」的约定。同时 `src/triage_rules.py` 的 `DEFAULT_RULES` 与出厂 `config/triage-rules.json` 是两份真相，config 被改后代码内默认值悄悄过期。

## What Changes

- `config/triage-rules.json` 的 `push.diff` 新增 `filenameIncludePatterns`（fnmatch 列表）：空列表保持现行为（added/removed 非空即推）；非空时仅推送命中模式的文件名，未命中项在正文注明剔除数量（与现有 suppress 剔除口径一致）。
- `config/intranet-versions.json` 的每个选择项新增可选 `mode` 字段：`substring`（默认，等价现行为）或 `fnmatch`；缺省时完全向后兼容。
- `src/triage_rules.py` 的 `DEFAULT_RULES` 收窄为仅能保证「规则文件损坏」告警可推送的最小规则集；业务默认值只存在于出厂 config 文件，消除双真相。
- `skills/ff-config-assistant/SKILL.md` 能力表同步收录上述新键，使 Claw 可对话式修改它们。
- design.md 记录「规则解释器/DSL」作为未来方向（当优先级编排或新事实维度类需求反复出现时再立项），本变更不实施。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `py-notifier-loop`: diff 重要性判定新增 include 维度（`push.diff.filenameIncludePatterns`）；内置兜底规则收窄为最小自愈集。
- `configurable-version-snapshot-logs`: 版本匹配文本新增可选匹配模式（substring 默认 / fnmatch）。
- `ff-config-assistant`: 白名单能力表收录 `filenameIncludePatterns` 与版本 `mode` 两个新键。

## Impact

- 代码：`src/triage_rules.py`（校验 schema、判定/过滤逻辑、DEFAULT_RULES）、`src/intranet_filename_monitor.py`（`load_selected_versions`、`filter_version_files`）。
- 配置：`config/triage-rules.json`、`config/triage-rules.example.json`、`config/intranet-versions.json`、`config/intranet-versions.example.json`（新增键均为可选/默认空，现有配置无需改动即兼容）。
- 文档：`skills/ff-config-assistant/SKILL.md` 能力表与规则细节、`AGENTS.md` 规则一节相应更新。
- 测试：`tests/test_triage_rules.py`、`tests/test_intranet_filename_monitor.py` 增加新键的校验与判定用例。
- 无新依赖；通知器与采集器的热读机制不变，落盘下一轮生效。
