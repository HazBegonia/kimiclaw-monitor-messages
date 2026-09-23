# skill-driven-requirement-lifecycle Specification (delta)

## REMOVED Requirements

### Requirement: SKILL.md 采集需求段为唯一需求来源

**Reason**: 需求的检测、确认与代笔写入全部依赖 OpenClaw 会话（claw 定时任务与 @FF 交互），随 openclaw 整体退役暂停。
**Migration**: SKILL.md「采集需求」节原样保留为文档与将来重建的入口；过渡期监控需求变更直接人工编辑 `config/monitors.json`、`config/intranet-versions.json` 与计划任务参数。

### Requirement: 需求变更检测

**Reason**: skillHash 比对由 claw 定时任务执行，执行者已退役。
**Migration**: 通知器重建需求闭环的后续 change 将以 py 实现等价的变更检测。

### Requirement: 理解回显与确认闸

**Reason**: 需求翻译、群确认消息发送与「开始」指令接收均依赖 OpenClaw 会话。
**Migration**: 过渡期需求变更不设确认闸（人工编辑即意图本身）；恢复路径由后续 change 承载。

### Requirement: 需求台账

**Reason**: 台账的状态流转由 claw 驱动；执行者退役后台账转为静态审计记录。
**Migration**: `state/requirements.json` 原样保留（含 2026-09-17 的三条「待确认」与全部历史），供审计与将来重建时续用。

### Requirement: 需求无过期

**Reason**: 同需求台账——生命周期驱动者退役，条款随能力暂停一并移除。
**Migration**: 台账保留期间无任何流程改写它；重建时再议过期策略。

### Requirement: config 生成幂等

**Reason**: config 生成者（claw）退役。
**Migration**: 过渡期 config 由人工维护，不存在自动重写或覆盖。

### Requirement: 扫描频率纳入需求管理

**Reason**: 频率字段的激活链路（确认→同步→重建任务）依赖 claw。
**Migration**: 扫描频率过渡期经注册脚本参数人工维护，见 system-scheduled-scan delta。
