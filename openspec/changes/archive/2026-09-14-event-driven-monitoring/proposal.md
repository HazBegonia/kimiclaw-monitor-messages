# Proposal: event-driven-monitoring

## Why

当前 triage（重要性判定 + 企微推送）由 OpenClaw cron 的 agent 任务**每分钟定时轮询**驱动：无论有没有新产物，每小时都烧 60 轮 agent token（估算 3000-6000 万 token/天），其中绝大多数轮次空手而归。内网文件实际更新频率很低，轮询模型的成本与价值严重不匹配。同时扫描调度挂在 OpenClaw cron 上，gateway 一停全部停摆。

## What Changes

- **事件驱动 triage（B 方案）**：py 扫描脚本检测到新 diff 日志或新错误日志时，直接 spawn `openclaw agent --local -m "<triage指令>"` 唤醒 claw 做一轮 triage；没有新产物则全程零 token。唤醒失败时事件进 outbox 队列，py 下次运行时重试（自愈，不丢事件）。
- **扫描调度迁移到 Windows 计划任务**：新增注册脚本由系统级计划任务每分钟跑 py（0 token），替代 OpenClaw cron 的扫描命令任务；迁移遵循单调度器铁律（先建新的 → 验证 → 删旧的）。
- **OpenClaw cron 兜底降频**：保留的 notify agent 任务从每分钟降为每 10 分钟，职责收窄为 skillHash 需求同步（变更检测 + @FF 控制指令处理）+ outbox/游标扫尾。
- **需求确认闭环延伸一步**：需求被 @FF 确认激活后，claw 除更新 config 外，还负责注册/更新 Windows 计划任务；「采集需求」块新增 `scanIntervalMinutes` 字段（默认 1 分钟），监视频率纳入 skill 管理。
- **错误日志纳入事件链**：flow2 的 `record_error` 写入错误日志后同样触发唤醒事件；py 保持哑，重要性判定仍全部归 claw 按 skill 规则执行。
- **并发互斥与事件合并**：`state/triage.lock` 保证同一时刻只有一个 triage 会话；同一分钟多个目标出事只唤醒一次（agent 天然扫全部新产物）；outbox 有积压时先重发不重复起进程。

## Capabilities

### New Capabilities

- `event-driven-triage`: py 扫描产物（diff/错误日志）主动唤醒 claw 的事件机制——spawn 通道、outbox 自愈重试、事件去重与合并、triage 互斥锁。
- `system-scheduled-scan`: 由 Windows 计划任务承载扫描调度的注册与生命周期管理，含单调度器铁律与 claw 在需求确认后注册/更新计划任务的职责。

### Modified Capabilities

- `skill-driven-requirement-lifecycle`: 需求确认激活后新增「注册/更新 Windows 计划任务」动作；「采集需求」机器可读块新增 `scanIntervalMinutes` 字段；兜底 cron 从每分钟 triage 轮询降为 10 分钟需求同步 + 扫尾。

## Impact

- **代码**：`src/intranet_filename_monitor.py`（事件机制从 HTTP POST 扩展为 spawn agent、record_error 接入事件、节流合并）；新增 `scripts/register-windows-scheduler.ps1`；`scripts/run-intranet-monitor.ps1` 可能微调。
- **配置**：SKILL.md「采集需求」块加 `scanIntervalMinutes`；`config/monitors.json` 结构不变；OpenClaw cron 的 notify 任务 prompt 与频率调整（`config/openclaw-intranet-cron.json` + `scripts/register-openclaw-intranet-cron.ps1`）。
- **状态文件**：新增 `state/triage.lock`；`state/openclaw-pending/` outbox 语义扩展为 spawn 失败队列。
- **skill**：`skills/intranet-message-triage/SKILL.md` 增加事件驱动触发说明、互斥规则、计划任务管理规则。
- **运维**：gateway 仍须常驻（spawn agent 依赖它）；Windows 计划任务在当前用户会话下运行，注销后行为需演练验证。
- **成本**：agent token 消耗从千万级/天降至百万级/天（约 95%+ 降幅）；风险是事件链路故障时告警延迟退化为兜底频率（≤10 分钟）。
