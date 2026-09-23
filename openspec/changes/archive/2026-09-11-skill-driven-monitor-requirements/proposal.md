# Proposal: skill-driven-monitor-requirements

## Why

当前监控系统的规则散落在两处且定位错位：采集需求（盯哪个页面、关注哪个版本号）固化在脚本参数与手工维护的 config 里，重要性判断写在 SKILL.md 里，而 `logs/intranet-focus/` 的版本快照没有任何下游消费。真实业务中规则由上级动态定义，需要一个"人只改 SKILL.md、claw 理解后经人确认再落地执行"的闭环，同时把脚本退化为不理解语义的哑采集器，避免规则变更改代码、避免 claw 未确认就改变系统行为。

## What Changes

- SKILL.md（intranet-message-triage）新增**采集需求**一节，作为全部采集类需求的唯一来源（监控目标 URL、关注版本清单）；人通过改这一节提出或变更需求。
- claw 的每分钟 cron 任务新增**需求同步**步骤：检测采集需求段变化（skillHash 比对）→ 理解并生成最终执行形态 → 通过 FF 机器人发群确认消息 → 仅当人在群内 @FF 回复「开始」后激活 → 由已激活需求生成/覆盖 `config/*.json`。需求不过期，skill 不动需求不变。
- 新增 @FF 交互会话的**控制指令**能力：只认 `开始` / `暂停` / `状态` 三个指令，其余消息不执行任何动作；需求内容本身不可通过群聊变更。
- 新增 `state/requirements.json` 需求台账：记录每条需求的最终执行形态、状态（待确认/已激活/已暂停/已被取代）、提出与确认时间、skillHash。config 只由"已激活"需求生成，手工改 config 会被同步覆盖。
- 脚本定位调整为哑采集器：全量 diff、版本 focus 快照、错误日志均为原始材料，不做重要性判断；focus 快照的用途（在架清单 / 变更核对）由 SKILL.md 规则决定。
- 脚本支持**多监控目标**：`config/monitors.json` 驱动 URL 列表，每个目标独立的 state 与日志；当前只有单个页面时配置退化为单条目。
- SKILL.md 的输入表补上 `logs/intranet-focus/`，打通现存的断链。
- 重要性判定规则继续留在 SKILL.md，改动不过确认闸（只影响 claw 自身判断，不碰脚本行为）。

## Capabilities

### New Capabilities

- `skill-driven-requirement-lifecycle`: SKILL.md 采集需求段为唯一需求来源；claw 检测变化后理解、回显最终执行形态、群内经 @FF 确认后激活；台账记录状态机；仅已激活需求同步为机器可读 config。
- `wecom-bot-control-commands`: @FF 触发的交互会话只处理 `开始` / `暂停` / `状态` 控制指令并回执，不承接需求内容变更。
- `configurable-monitor-targets`: 脚本从 `config/monitors.json` 读取监控目标列表（URL + 每目标字段提取 profile），逐目标独立采集、独立 state 与 diff 日志，单目标时行为与现状一致。

### Modified Capabilities

- `configurable-version-snapshot-logs`: 版本选择配置的**来源**变更——`config/intranet-versions.json` 由 claw 从已激活需求同步生成，不再手工维护；脚本读取配置与写快照的行为不变。

## Impact

- **代码**：`src/intranet_filename_monitor.py`（多目标循环、monitors.json 读取；版本过滤与 focus 逻辑复用不动）；`tests/test_intranet_filename_monitor.py`（多目标用例）。
- **Skill**：`skills/intranet-message-triage/SKILL.md`（新增采集需求、需求同步、控制指令三节；输入表加 focus）。
- **配置**：新增 `config/monitors.json`；`config/intranet-versions.json` 改由 claw 生成。
- **状态**：新增 `state/requirements.json` 台账。
- **OpenClaw cron**：`intranet-message-notify` 任务流程增加需求同步步骤；@FF 交互会话需实测验证（能否唤起、会话内能否读写项目文件与调 wecom-cli 发群消息）。
- **不做**：企业微信/钉钉消息源的接入；"这类不重要"的群聊自由反馈（群聊只走控制指令，需求变更只走改 SKILL.md）。
