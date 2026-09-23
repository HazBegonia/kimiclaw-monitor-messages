# event-driven-triage Specification (delta)

## REMOVED Requirements

### Requirement: 产物驱动唤醒

**Reason**: 唤醒对象（OpenClaw agent 会话）整体退役；判定与推送移入常驻通知器进程内按游标轮询执行，不再需要事件唤醒链。
**Migration**: 由 py-notifier-loop 的「游标消费采集产物」「通知器常驻任务」承载——无产物时同样零消息、零开销，且游标消费天然幂等。

### Requirement: 唤醒失败自愈（outbox）

**Reason**: outbox 承载的是唤醒事件的补偿；唤醒链路消失后，等价保障由游标语义天然承担（发送失败游标不推进，下轮重扫重发）。
**Migration**: `state/openclaw-pending/` 目录废弃；py-notifier-loop「发送成功才推进游标」覆盖同一保障。

### Requirement: 唤醒合并与节流

**Reason**: 判定收敛为单通知器进程内串行执行，每轮天然聚合全部新产物为一次处理，不存在多唤醒并发问题。
**Migration**: py-notifier-loop「单轮聚合单条推送」承载等价行为。

### Requirement: triage 互斥

**Reason**: triage 从多会话并发（事件唤醒、兜底轮、@FF 交互会话）变为单进程串行，文件级互斥锁失去存在前提。
**Migration**: `state/triage.lock` 废弃；并发防护由 py-notifier-loop「单实例运行」（进程级心跳锁）承担。

### Requirement: 兜底轮询扫尾

**Reason**: 兜底轮（OpenClaw cron）的三项职责分别有了新归宿：游标补扫并入通知器每轮消费（游标失败天然重试）；事件链故障检查由发送失败留痕与人工排障承接；skillHash 需求同步随需求闭环暂停（见 skill-driven-requirement-lifecycle delta）。
**Migration**: OpenClaw cron `intranet-message-notify` 停用；「事件链失效告警」的等价物是发送失败的持续留痕与下一轮自动重试。
