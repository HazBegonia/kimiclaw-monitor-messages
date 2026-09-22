# py-notifier-loop Specification

## Purpose

让重要性判定与企微推送彻底脱离 LLM 会话：常驻通知器以推送游标消费采集器落盘的 diff 与错误产物，按机器可读的确定性规则判定，聚合为单条消息经智能机器人直发目标群；失败留痕、不丢消息、不重复推送。

## Requirements

### Requirement: 游标消费采集产物

通知器 MUST 仅处理推送游标（`state/notify-state.json`）之后的产物：diff 日志按文件名（时间戳）排序，只取 `diffCursor` 之后的新 `.log`；错误日志按 `errorCursor` 的日期文件行偏移取新 JSONL 行，出现游标日期之后的日期文件时从其第 0 行开始。游标文件缺失或损坏 MUST 视为空游标并从全部产物开始处理，不得因此静默丢弃或跳过产物。

#### Scenario: 增量消费

- **WHEN** `diffCursor` 指向文件 F，目录中出现 F 之后命名的两个新 diff 文件
- **THEN** 本轮仅收集并评估这两个新文件

#### Scenario: 跨天错误消费

- **WHEN** 错误日志出现新日期文件且游标仍指向前一日期的行偏移
- **THEN** 新日期文件从第 0 行开始全部纳入本轮评估

### Requirement: 确定性规则判定

重要性判定 MUST 由规则文件 `config/triage-rules.json` 驱动，每轮热读（修改后下一轮生效，无需重启）；判定 MUST 只依赖产物中的结构化字段（diff 的 added/removed 文件名、错误的 monitorId/phase/errorType/retryable/statePreserved），MUST NOT 发起任何 LLM 调用。文件新增（added 非空）与删除（removed 非空）默认判为重要；错误按 errorType 与 phase 命中规则判为重要；未命中任何规则的事实按规则文件的 unmatched 兜底策略处理（diff 兜底为推、错误兜底为不推）。

#### Scenario: 规则热读生效

- **WHEN** 人在通知器运行期间修改规则文件并保存
- **THEN** 下一轮判定按新规则执行，进程未重启

#### Scenario: 新增文件判重要

- **WHEN** 新 diff 产物记录 added 非空且未命中抑制规则
- **THEN** 该事实判为重要，进入本轮聚合

#### Scenario: 未命中错误走兜底

- **WHEN** 一条错误记录的 errorType 与 phase 均不在规则列表中
- **THEN** 按 unmatched 兜底策略判定（默认不推送）

### Requirement: 规则文件自愈

规则文件缺失、非法 JSON 或不符合约定结构时，通知器 MUST 继续使用最近一次加载成功的规则判定，并产生一条「规则文件损坏」的自身错误事实；该事实 MUST 被现行规则判为重要（监控器自身错误），使群内收到规则损坏告警而不是静默失效。

#### Scenario: 半截保存不中断

- **WHEN** 规则文件被人保存为非法 JSON
- **THEN** 本轮判定沿用上一份好规则，群内收到规则文件损坏的告警

### Requirement: 孤立抖动抑制与重复升级

错误记录同时满足 `retryable=true` 且 `statePreserved=true` 时 MUST 判为不重要（孤立网络抖动）；但同一 `monitorId` 与 `phase` 的此类错误在规则配置的时间窗口内达到阈值次数时，MUST 升级为重要并进入推送。窗口计数 MUST 仅在进程内存中维护，通知器重启后从零重新累计。

#### Scenario: 单次超时不推

- **WHEN** 窗口内某目标仅出现一条 retryable 的 fetch 阶段超时错误
- **THEN** 该错误被抑制，群内无推送

#### Scenario: 窗口内重复升级

- **WHEN** 同一目标的 fetch 阶段错误在窗口秒数内累计达到阈值（如 3 次）
- **THEN** 升级为重要，群内收到聚合后的错误告警

### Requirement: 单轮聚合单条推送

每轮评估出的全部重要事实 MUST 聚合为一条 markdown 推送，沿用既有模板（来源行、新增文件段、删除文件段、错误段、目录链接）；单段超过 15 条时 MUST 截断并列出剩余数量；错误摘要每条不超过 80 字符；正文总长不得超过 20480 UTF-8 字节，超出时进一步截断并注明。无重要事实的轮次 MUST NOT 发送任何消息。

#### Scenario: 多事实一条消息

- **WHEN** 同轮出现两个目标的新增文件与一条重要错误
- **THEN** 群内只收到一条包含全部内容的聚合消息

#### Scenario: 无事不打扰

- **WHEN** 本轮无新产物或全部产物判为不重要
- **THEN** 群内不收到任何消息，游标照常推进

### Requirement: 发送成功才推进游标

推送发送成功后 MUST 才推进游标（`diffCursor` 到本轮最后处理的 diff 文件名，`errorCursor` 到已处理的日期与行数）；发送失败（网络异常、认证失败、发送回执非 0、超时）MUST 向 `logs/intranet-notify/` 当日文件追加一行包含失败原因与正文摘要的 JSONL 留痕，且游标保持不动，下一轮重新收集同一批产物并重试。判为不重要的事实处理完毕即计入游标推进，MUST NOT 因未推送而阻塞后续产物。

#### Scenario: 失败不丢消息

- **WHEN** 一次推送因网络异常失败
- **THEN** 留痕写入当日 JSONL，游标不动，下一轮自动重试同一批内容

#### Scenario: 重试不重复

- **WHEN** 上轮失败的内容在本轮重试成功
- **THEN** 群内只收到本轮这一条消息，游标一次推进到位

### Requirement: dry-run 与单次模式

通知器 MUST 支持 dry-run 模式：完整执行收集、判定与聚合，将拟发送的 markdown 打印到本地输出，不发起任何机器人连接、不推进游标。通知器 MUST 支持单次模式：处理一轮后退出，处理发生异常时以非零退出码退出，供计划任务与排障使用。

#### Scenario: 影子对照

- **WHEN** 以 dry-run 模式运行且存在重要产物
- **THEN** 本地输出聚合正文，群内无消息，游标不推进

#### Scenario: 单次退出码

- **WHEN** 单次模式下发生产物处理失败
- **THEN** 进程以非零退出码退出并留下错误记录

### Requirement: 单实例运行

常驻通知器 MUST 以心跳锁（`state/notifier-resident.lock`）保证同一时刻单实例：发现活锁时新实例安静退出；锁心跳超时视为陈旧，新实例 MUST 可接管；正常退出时清理锁文件。

#### Scenario: 双实例互斥

- **WHEN** 已有实例持活锁运行，第二个实例被启动
- **THEN** 第二个实例安静退出，不产生任何推送或游标副作用

#### Scenario: 陈旧锁接管

- **WHEN** 持锁实例死亡且心跳超时
- **THEN** 新实例删除陈旧锁并正常接管

### Requirement: 通知器常驻任务

通知器 MUST 由独立的 Windows 计划任务常驻承载（登录触发 + 周期性守护触发，与采集任务同构）；轮询间隔从 `config/notifier.json` 读取（缺省 5 秒）；注册脚本 MUST 幂等（重复注册更新既有任务而非创建重复任务）。通知器运行 MUST NOT 依赖 OpenClaw gateway 或任何 LLM 服务在线。

#### Scenario: 注册幂等

- **WHEN** 重复执行通知器任务注册脚本
- **THEN** 计划任务被更新，系统中不出现重复的通知器任务

#### Scenario: 崩溃自愈

- **WHEN** 通知器进程异常退出
- **THEN** 守护触发器在下一周期重新拉起，游标语义保证无丢失、无重复
