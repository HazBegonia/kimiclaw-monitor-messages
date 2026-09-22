# Tasks: event-driven-monitoring

## 1. py 唤醒机制（event-driven-triage 核心）

- [x] 1.1 新增 `--triage-message-file` 参数（默认 `config/triage-message.txt`）与读取逻辑，文件内容作为 spawn 的 `-m` 指令文本
- [x] 1.2 实现每轮结束统一唤醒：收集本轮"有新 diff / 有新错误"标记，全部目标扫描完成后 spawn 一次 `openclaw agent --local -m <指令>`；多目标同时出新产物只唤醒一次
- [x] 1.3 错误日志纳入唤醒标记：`record_error` 保持只写日志，主循环在错误发生后记录标记，与 diff 标记合并统一触发（不在 record_error 内 spawn）
- [x] 1.4 outbox 语义改造：spawn 失败将事件（含去重 event_id）写入 `state/openclaw-pending/`；每轮开始先重试投递存量；任意一次 spawn 成功即清除全部 outbox 文件
- [x] 1.5 新建 `config/triage-message.txt` 指令模板（项目根 + 读 SKILL.md 执行一轮 triage + 先取互斥锁），UTF-8 无 BOM

## 2. 测试与回归

- [x] 2.1 新增单测：无产物不唤醒、diff 触发唤醒、错误触发唤醒、多目标合并一次、spawn 失败入队、下轮重试成功清队、重复事件去重
- [x] 2.2 既有测试全部回归通过（当前 24 个）

## 3. Windows 计划任务迁移（单调度器铁律）

- [x] 3.1 新建 `scripts/register-windows-scheduler.ps1`：`schtasks /create /tn KimiclawIntranetScan /sc minute /mo <间隔> /f` 幂等注册，调用 `run-intranet-monitor.ps1 -Mode Once`；脚本输出与任务名只用 ASCII
- [x] 3.2 运行注册脚本创建计划任务，手动 `schtasks /run` 验证能正常扫描并落盘 state 与日志
- [x] 3.3 验证通过后删除 OpenClaw cron 的 `intranet-file-monitor-once` 扫描任务（验证失败则保留旧任务并回滚）

## 4. 兜底 cron 降频

- [x] 4.1 `config/openclaw-intranet-cron.json`：`notifyEvery` 改为 `10m`
- [x] 4.2 `scripts/register-openclaw-intranet-cron.ps1`：notify prompt 收窄为"需求同步 → outbox 积压检查（超期告警）→ 游标落后则取锁补扫 → 零动作退出"，重跑注册脚本幂等更新

## 5. SKILL.md 更新

- [x] 5.1 增加触发方式说明：事件驱动为主（py spawn 唤醒）、兜底轮询为辅，triage 流程本身不变
- [x] 5.2 增加 triage 互斥锁规则：`state/triage.lock` 原子创建、`acquiredAt` 超 15 分钟可打破、结束释放；@FF 控制指令不取锁
- [x] 5.3 「采集需求」机器可读块增加 `scanIntervalMinutes`（缺省 1）；「需求同步」流程在激活后新增"调用 register-windows-scheduler.ps1 同步计划任务"步骤
- [x] 5.4 增加 outbox 积压告警规则：积压持续超过一个兜底周期 → 群内告警监控自身故障

## 6. 端到端演练与文档

- [x] 6.1 gateway 停机/恢复演练：停机期间扫描落盘正常、事件入队；恢复后 outbox 补投递、群收告警
- [x] 6.2 并发演练：事件唤醒与兜底轮同时触发 triage，验证互斥锁只有一个执行
- [x] 6.3 需求变更演练：改 SKILL.md 的 `scanIntervalMinutes` → @FF 确认 → 计划任务间隔更新
- [x] 6.4 验证锁屏/注销后计划任务是否照常运行（回答 design.md 的 Open Question）
- [x] 6.6 消除每分钟弹出的控制台黑窗口：任务命令改为 `conhost.exe --headless powershell.exe ...`（Win11 24H2+），重新注册并验证
- [x] 6.5 更新 AGENTS.md 与 wiki（架构与 workflow 描述同步为事件驱动）
