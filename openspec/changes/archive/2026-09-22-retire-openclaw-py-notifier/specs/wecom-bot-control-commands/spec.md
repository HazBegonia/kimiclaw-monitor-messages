# wecom-bot-control-commands Specification (delta)

## REMOVED Requirements

### Requirement: 受限指令集

**Reason**: @FF 消息唤起的交互会话整体依赖 OpenClaw，随 openclaw 退役冻结；通知器本阶段为按需连接、不接收消息。
**Migration**: py 通知器架构已预留常驻连接升级路径；指令接收与逐字匹配（确定性、无需 LLM）的重建由后续 change 承载。

### Requirement: 开始指令

**Reason**: 指令处理者（LLM 会话）退役，且其作用对象（需求确认闸）同步暂停。
**Migration**: 随 skill-driven-requirement-lifecycle 的重建一并恢复。

### Requirement: 暂停指令

**Reason**: 同上，作用对象与执行者均已暂停。
**Migration**: 过渡期暂停监控直接注释/移除 `config/monitors.json` 中的目标（采集器支持空目标安静空转），或停用对应计划任务。

### Requirement: 指令处理留痕

**Reason**: 指令链路整体冻结。
**Migration**: 台账的状态变更时间戳随历史保留；重建指令能力时恢复留痕要求。
