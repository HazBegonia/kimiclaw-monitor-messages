# Design: event-driven-monitoring

## Context

现状（动机见 proposal.md）：

- py 扫描脚本（`src/intranet_filename_monitor.py`）已有 dormant 的 HTTP 事件机制：`--event-url` POST + outbox 队列（`state/openclaw-pending/`）+ `deliver_pending` 重试，但只覆盖 diff 日志，且当前部署未配置 event-url。
- 调度全部由 OpenClaw cron 承载：`intranet-file-monitor-once`（命令任务，每分钟跑 `scripts/run-intranet-monitor.ps1 -Mode Once`）+ `intranet-message-notify`（agent 任务，每分钟 triage）。
- 需求闭环已成立：SKILL.md「采集需求」块 → skillHash → 台账 → @FF 确认 → config 照抄生成。
- 约束：gateway 常驻在同一用户会话；`openclaw agent --local -m "<指令>"` 已在 smoke 测试中验证可用（依赖 gateway 在线）；企微发送走 wecom-cli tool（本设计不涉及）。

## Goals / Non-Goals

**Goals:**

- py 有新产物（diff/错误日志）时 spawn 一次性 agent 会话唤醒 claw；无产物零 token。
- 扫描调度迁移到 Windows 计划任务，gateway 停机时采集不中断。
- 兜底 cron 降为 10 分钟，职责收窄为需求同步 + 扫尾。
- triage 并发互斥；事件链失效可自愈、可观测。

**Non-Goals:**

- gateway HTTP 事件入口（A 方案）——留作后续 spike，不在本 change。
- 重要性判定规则、企微推送通道、config 结构（targets/versions 部分）——均不变。
- 多机部署、无人值守（注销后运行）加固——只演练验证，不实现。

## Decisions

### D1：唤醒通道 = py spawn `openclaw agent --local`

选 B 方案（已验证可行），放弃 A 方案（gateway HTTP 入口未验证）。py 每轮扫描结束后统一决策：本轮有新 diff 或新错误日志 → spawn 一次；否则不动作。

- py 新增参数 `--triage-message-file`（默认 `config/triage-message.txt`），文件内容即 spawn 的 `-m` 指令文本。指令模板与现 notify cron prompt 同源：项目根 + 读 SKILL.md 执行一轮 triage + 互斥锁要求。独立文件而非 py 内嵌，让 claw 在需求确认时可同步更新它。
- py 保持哑：`-m` 文本不含重要性判断，只陈述"有新产物，按 skill 执行一轮"。
- 备选：复用 `--event-url` POST 到 gateway。否决：接口未验证，且 POST 成功不等于 agent 真的执行了 triage。

### D2：outbox 语义 = 「唤醒信号」的持久化，投递成功即全部清除

triage 按游标读取**全部**新产物，所以一次成功唤醒天然覆盖所有积压事件。由此简化：

- 唤醒失败 → 写一个事件文件进 outbox（event_id 仍用去重哈希，避免同一事件重复入队）。
- py 每轮开始先 `deliver_pending`：重试 spawn；**任意一次 spawn 成功即清除全部 outbox 文件**（ claw 会扫游标后所有产物，逐一投递无意义）。
- 备选：逐事件投递、claw 消费后回执删除。否决：需要 claw 回写协议，复杂度不值——游标机制已经是幂等事实源。

### D3：错误日志纳入唤醒，但单点触发

`record_error` 保持只写日志不触发动作；主循环在 `run_once` 返回/异常后记录"本轮有新错误"标记，一轮全部目标扫描结束后与 diff 标记合并，统一 spawn 一次。避免一条错误一个电话的轰炸。

### D4：互斥锁 `state/triage.lock`

- 获取：原子创建（`O_EXCL` 语义），内容 `{pid, acquiredAt}`；已存在则读取 `acquiredAt`，超过 15 分钟视为遗留锁，允许打破（删除后重试一次）。
- 释放：triage 正常结束删除锁文件。
- 适用所有 triage 来源：事件唤醒会话、兜底 cron、@FF 交互会话。@FF 控制指令（开始/暂停/状态）不涉及游标，不取锁，台账仍按现有"原子写 + 写前重读"约定。
- 锁逻辑写进 SKILL.md（claw 侧遵守），不靠 py 强制。

### D5：Windows 计划任务注册脚本

新增 `scripts/register-windows-scheduler.ps1`（仿 `register-openclaw-intranet-cron.ps1` 风格）：

- 用 `schtasks /create /tn "KimiclawIntranetScan" /sc minute /mo <scanIntervalMinutes> /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File <run-intranet-monitor.ps1> -Mode Once" /f`。`/f` 覆盖同名任务，天然幂等。
- 当前用户权限注册，无需管理员；工作目录由 ps1 内部 `Push-Location $workspace` 保证（现状已是）。
- `scanIntervalMinutes` 从已激活需求读取，claw 确认激活后调用该脚本同步；缺省 1。
- 备选：`Register-ScheduledTask`（更精细，可配登录态）。否决为默认方案：参数复杂、当前场景 schtasks 足够；注销后运行需求留 Open Question。

### D6：兜底 cron 降频与 prompt 收窄

`config/openclaw-intranet-cron.json` 的 `notifyEvery` 改为 `10m`；notify prompt 改为：需求同步（skillHash）→ 检查 outbox 积压（超一个周期则告警）→ 检查游标是否落后 logs（落后则取锁补扫一轮）→ 零动作退出。declaration-key 不变，重跑注册脚本即幂等更新。

### D7：迁移顺序（单调度器铁律）

1. 实现并测试 py 唤醒机制（旧 OpenClaw cron 原样运行）。
2. `register-windows-scheduler.ps1` 注册计划任务 → 手动 `schtasks /run` 验证扫描落盘正常。
3. 删除 OpenClaw cron 的 `intranet-file-monitor-once`。
4. 更新兜底 cron（降频 + 新 prompt）。
5. 更新 SKILL.md（事件驱动说明、锁规则、`scanIntervalMinutes`）。
6. 端到端演练：gateway 停机恢复、并发触发、需求变更改频率。

回滚：删除计划任务，重跑 `register-openclaw-intranet-cron.ps1` 恢复原两个 cron 任务。

## Risks / Trade-offs

- [gateway 停机则唤醒失败] → outbox 持久化 + py 每轮重试 + 兜底轮 10 分钟补扫，告警最多延迟一个兜底周期。
- [spawn 冷启动开销（秒级）与进程资源占用] → 一轮最多一次唤醒、outbox 积压时不叠加；diff 风暴场景上限 = 每分钟一次 spawn，可接受。
- [事件链全断导致告警静默] → 兜底轮检测游标落后补处理 + outbox 超期告警群消息，故障可观测。
- [Windows 计划任务在用户注销后不运行] → 演练验证锁屏/注销行为；当前 gateway 本就依赖同一会话常驻，风险等级相同；若需无人值守再升级到 `Register-ScheduledTask` + S4U。
- [锁会话异常退出导致 triage 永久阻塞] → 锁带 `acquiredAt`，15 分钟过期可打破。
- [schtasks 在 GBK 控制台的中文输出乱码] → 注册脚本输出与任务名只用 ASCII/英文。

## Open Questions

- 用户注销/锁屏后计划任务是否照常运行（演练验证；不行则升级 `Register-ScheduledTask -LogonType S4U`）。
- `openclaw agent --local` 并发上限与内存占用（上线后观察）。
- A 方案（gateway HTTP 事件入口）是否值得后续 spike 以进一步降低唤醒延迟。
