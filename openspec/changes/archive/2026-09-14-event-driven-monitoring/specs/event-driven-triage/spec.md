# event-driven-triage Specification (delta)

## Purpose

让重要性判定与企微推送（triage）由监控产物驱动：py 扫描脚本检测到新 diff/错误日志时才唤醒 claw，无产物时零 token；同时保证事件不丢、不重复、不并发撞车，事件链失效时有低频兜底。

## ADDED Requirements

### Requirement: 产物驱动唤醒

py 每轮扫描结束后，若本轮产生了新 diff 日志或新错误日志，MUST 通过 spawn 一次性 agent 会话（`openclaw agent --local -m "<固定 triage 指令>"`）唤醒 claw 执行一轮 triage；无新产物时 MUST NOT 发起任何 agent 会话。py MUST 保持哑：唤醒信号只携带客观事实（监控目标、日志路径、检测时间），不得包含重要性判断。

#### Scenario: diff 日志触发唤醒

- **WHEN** 一轮扫描为某目标写出了新 diff 日志
- **THEN** py 在完成全部目标扫描后 spawn 一次 triage agent 会话

#### Scenario: 错误日志触发唤醒

- **WHEN** 一轮扫描写入了新错误日志（flow2）
- **THEN** py 同样触发唤醒，该错误是否重要由 claw 按 skill 规则判定

#### Scenario: 无变化静默

- **WHEN** 一轮扫描无新 diff 且无新错误日志
- **THEN** py 不发起任何 agent 会话，本轮 token 消耗为零

### Requirement: 唤醒失败自愈（outbox）

唤醒失败（spawn 非零退出、OpenClaw gateway 不在线等）MUST 将事件写入本地 outbox 队列（`state/openclaw-pending/`）；py 后续每次运行 MUST 先重试投递 outbox 中的存量事件，投递成功才将其移除。事件 MUST 携带稳定去重 ID，同一事件被重复投递 MUST NOT 造成群内重复推送。

#### Scenario: 唤醒失败入队

- **WHEN** spawn agent 失败（如 gateway 停机）
- **THEN** 事件写入 outbox，本轮扫描的 state 与日志落盘不受影响

#### Scenario: 恢复后重试投递

- **WHEN** 下一次 py 运行时唤醒通道恢复可用
- **THEN** outbox 中积压事件被重新投递，成功后从队列移除

#### Scenario: 重复投递不重复推送

- **WHEN** 同一事件因重试被投递多次
- **THEN** 因 triage 按游标读取日志，群内不收到重复告警

### Requirement: 唤醒合并与节流

同一轮扫描中多个监控目标均产生新产物时，MUST 合并为一次唤醒（triage 天然处理游标后的全部新产物）；outbox 存在未投递事件时，MUST 优先重试存量事件而不是并发发起新唤醒。

#### Scenario: 多目标合并为一次唤醒

- **WHEN** 同一轮扫描中两个以上目标都写出新 diff 日志
- **THEN** py 只 spawn 一次 triage agent 会话

#### Scenario: 积压时不叠加唤醒

- **WHEN** outbox 非空且本轮又有新产物
- **THEN** py 重试投递存量事件，不并发起多个 agent 会话

### Requirement: triage 互斥

任何触发来源（事件唤醒、兜底轮询、@FF 交互会话）执行 triage 前 MUST 先取得互斥锁（`state/triage.lock`）；未取得锁的会话 MUST 直接退出，不读取也不推进游标。锁持有者异常退出时，遗留锁 MUST 不永久阻塞后续 triage。

#### Scenario: 并发触发只执行一个

- **WHEN** 两个 triage 会话近乎同时被触发
- **THEN** 只有一个取得锁并执行，另一个直接退出

#### Scenario: 遗留锁可恢复

- **WHEN** 持锁会话异常退出、锁文件残留
- **THEN** 后续 triage 能在锁过期机制下继续执行，不永久卡死

### Requirement: 兜底轮询扫尾

系统 MUST 保留一个低频兜底轮询（频率 ≤10 分钟），职责限于：skillHash 需求同步与 @FF 控制指令处理、游标落后检测与补处理、outbox 积压检查。无需求变更、无新产物且 outbox 为空时，兜底轮 MUST 零动作退出。事件链持续失效 MUST 作为监控系统自身故障向群内告警。

#### Scenario: 兜底轮静默

- **WHEN** 无需求变更、游标无落后、outbox 为空
- **THEN** 兜底轮零动作退出，不发送任何群消息

#### Scenario: 漏处理补扫

- **WHEN** 兜底轮发现推送游标落后于 logs 中的新产物（事件链漏处理）
- **THEN** 兜底轮执行一轮完整 triage 补处理并按正常规则推送

#### Scenario: 事件链失效告警

- **WHEN** outbox 积压持续超过一个兜底周期（唤醒通道持续失败）
- **THEN** 群内收到一条监控系统自身故障的告警消息
