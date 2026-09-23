# Proposal: retire-openclaw-py-notifier

## Why

OpenClaw 把监控链路里最贵的一段变成了例行公事：每个 diff/错误事件唤醒一场 LLM triage 会话，兜底 cron 每 10 分钟再开一场，实测把 Kimi For Coding 周配额烧穿，`optimize-monitor-latency` 的收尾任务（7.2）因此停摆。而 triage 这段的实质——按重要性规则筛选日志产物、聚合成一条 markdown、经企微智能机器人 FF 推群——全部是确定性流程，本不需要任何 LLM；且官方 `@wecom/aibot-node-sdk`（MIT 开源，本机已随插件安装）证明机器人长连接协议可由 py 直接实现。

## What Changes

- 新增**通知器程序**（`python -m src.intranet_notifier`）：常驻轮询游标之后的 diff/错误日志产物 → 按规则引擎判定重要性 → 聚合为一条 markdown → 经企微智能机器人长连接（py 原生 WebSocket 客户端）直发 FF 所在群 → 成功才推进游标。全链路 0 token。
- 采集器 `src/intranet_filename_monitor.py` **代码零改动**：仅把 `config/triage-message.txt` 清空，停用事件唤醒（配置开关，非代码变更）。
- 新增**确定性规则引擎**：重要性规则从 SKILL.md（供 LLM 阅读）迁移为机器可读的 `config/triage-rules.json`，每轮热读；现行规则语义逐条平移。
- 新增**企微智能机器人 py 客户端**：实现官方长连接协议四帧（subscribe/ping/send_msg/respond_msg），v1 采用按需连接（有重要消息才连、发完即断），凭证存 gitignored 的 `state/secrets/`。
- **BREAKING** 整体弃用 OpenClaw：停 gateway、删兜底 cron `intranet-message-notify`、删每日会话压缩任务 `KimiclawSessionCompact`；随之冻结（后续 change 恢复）：@FF 五指令、对话草案、需求确认闸与 config 自动派生——过渡期 `config/monitors.json`、`config/intranet-versions.json`、扫描间隔改为人工维护。
- 退役：事件唤醒链（outbox `state/openclaw-pending/`、`state/triage.lock`）、wecom-cli tool 发送路径。需求台账 `state/requirements.json` 原样保留作审计与将来重建的基础。
- 新增第二个 Windows 常驻计划任务承载通知器（守护触发器模式与采集任务同构），注册脚本泛化为可参数化任务名/入口。
- 一次成型、刻意留缝：解析器/规则/渲染/发送四段流水线均为插件点；@FF 指令接收、需求闭环、语义规则等后续能力均以"加插件"方式接入，不动骨架。

## Capabilities

### New Capabilities

- `py-notifier-loop`: 通知器主循环——游标消费、事实解析、规则评估、聚合渲染、单条推送、失败留痕与重试、dry-run/单次模式、单实例锁、Windows 常驻任务。
- `wecom-aibot-ws-client`: 企微智能机器人 py WebSocket 客户端——协议帧、认证与回执、按需连接生命周期、独占连接约束、凭证管理（密钥不入仓库）。

### Modified Capabilities

- `event-driven-triage`: 全部 5 条需求移除——产物驱动唤醒、outbox 自愈、唤醒合并节流、triage 互斥锁、兜底轮询随 openclaw 退役；后继行为由 `py-notifier-loop` 承载（游标补扫天然幂等，不再需要唤醒链）。
- `wecom-aibot-notify`: 渠道建立方式从 OpenClaw 渠道改为 py 原生客户端；目标会话 chatid 从回调学习改为配置维护（激活前提"群内须有人 @FF 过"不变）；推送、频控、失败留痕的需求语义不变。
- `system-scheduled-scan`: 调度同步从"claw 驱动"改为人工执行注册脚本；"扫描不依赖 gateway"需求中去掉唤醒入队子句。
- `skill-driven-requirement-lifecycle`: 全部需求移除——需求同步自动化暂停；SKILL.md「采集需求」节保留为文档与将来重建入口，台账保留审计。
- `chat-driven-skill-config-editing`: 全部需求移除——@FF 自然语言草案依赖 LLM 会话，随 openclaw 退役冻结。
- `wecom-bot-control-commands`: 全部需求移除——@FF 指令依赖 LLM 会话，随 openclaw 退役冻结；恢复路径（常驻连接接收）已在通知器架构中预留。
- `configurable-version-snapshot-logs`: 版本配置从"claw 依据台账生成、手改被覆盖"改为过渡期人工维护；采集行为需求不变。

## Impact

- **代码**：新增 `src/intranet_notifier.py`、`src/triage_rules.py`、`src/wecom_bot_client.py`、`scripts/run-intranet-notifier.ps1`、PoC 脚本；`scripts/register-windows-scheduler.ps1` 泛化（`-TaskName`/`-EntryScript` 参数，默认值保持现行为）；采集器与现有测试不动。
- **依赖**：新增 py 依赖 `websocket-client`（纯 py 小库）；移除运行时对 Node/openclaw gateway 的依赖（仅回滚时需要）。
- **配置**：新增 `config/notifier.json`、`config/triage-rules.json`、`state/secrets/wecom-bot.json`；清空 `config/triage-message.txt`；退役 `config/openclaw-intranet-cron.json`。`~/.openclaw/openclaw.json` 原样保留（回滚基础）。
- **运维**：切换顺序铁律——先停 gateway（同一 botId 服务端只认一条活连接，互踢）再上通知器；新增 `KimiclawIntranetNotifier` 计划任务；删除两个旧任务/cron。影子验证用新建 dev 机器人进行，FF 与生产群在切换前零影响。
- **文档**：AGENTS.md、docs/workflow.md、docs/intranet-file-monitor.md 同步；SKILL.md 标注退役与规则迁移去向。
- **关联 change**：`optimize-monitor-latency` 仅剩的 7.2 因链路被替换而失去意义，建议随本 change 归档（其已完成的模型切换、常驻化成果被本方案直接继承）。
- **风险**：协议实现正确性（PoC + dev 机器人先行验证）；切换窗口监控空窗（顺序化操作，分钟级）；bot 失联期间告警不可达（与现状一致，留痕可查）。
