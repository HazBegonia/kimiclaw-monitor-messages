## 1. 模型切换（kimi-k2.6）

- [x] 1.1 在 `~/.openclaw/openclaw.json` 的 provider `kimi-coding` models 列表注册 `kimi-k2.6`，用 `openclaw agent --local --model kimi-coding/kimi-k2.6 -m <测试消息>` 验证可用；验证失败则恢复原配置、回报用户并终止本组任务
- [x] 1.2 将 `agents.defaults.model.primary` 切换为 `kimi-coding/kimi-k2.6`，发一条测试消息确认主 agent 走新模型

## 2. C2 spike：hook 可行性验证

- [x] 2.1 阅读 bundled hook `weixin-contact-monitor` 的 HOOK.md 与 handler.js（`~\Desktop\program\oc\openclaw-hooks\weixin-contact-monitor\`），整理 `message:received` hook 的 API：事件载荷结构、回复能力、能否吞掉消息、注册方式
- [x] 2.2 判定两个一票否决问题：handler 能否吞掉消息（避免 LLM 重复回复）、能否主动向企微群回复；任一不可行则在 change 中记录结论并关闭第 5 组任务，指令路径保持 LLM 处理

**Spike 结论（2026-09-16）**：一票否决，hook 路线不可行。依据 openclaw 官方文档 `docs/automation/hooks.md`（C:\Tools\npm-global\node_modules\openclaw）：(1) 内部 hook 是副作用观察器，无 block/cancel 语义，消息必然继续进入 agent 会话，吞不掉；(2) `event.messages` 仅 `command:new`/`command:reset`/`session:compact:*` 会投递，`message:*` 事件一律忽略，无法经 hook 回复群。两问皆否 → 第 5 组关闭，五指令保持 k2.6 LLM 会话处理。

## 3. py 常驻化改造

- [x] 3.1 `src/intranet_filename_monitor.py` 增加常驻单实例心跳锁（`state/monitor-resident.lock`，原子创建、每轮刷新、超 2 个周期可接管，发现活锁安静退出）
- [x] 3.2 空 targets 安静空转：`load_monitors_config` 允许合法空数组（空转跳过），文件缺失/损坏仍报 `read_config` 错误；`--once` 模式行为不变
- [x] 3.3 更新 `tests/test_intranet_filename_monitor.py` 覆盖：活锁退出、死锁接管、空 targets 空转、空数组不报错
- [x] 3.4 全套测试通过：`python -m pytest tests/ -q`

## 4. 常驻守护任务迁移

- [x] 4.1 改造 `scripts/register-windows-scheduler.ps1`：用 `Register-ScheduledTask` 注册登录触发、失败自动重启、`MultipleInstancesPolicy=IgnoreNew`、隐藏 PowerShell 的常驻守护任务，支持 `-IntervalSeconds` 参数
- [x] 4.2 注册并手动触发验证：常驻进程运行、5s 轮询正常落盘、无双实例、无可见窗口
- [x] 4.3 验证通过后删除旧的每分钟 tick 任务 `KimiclawIntranetScan`（单调度器铁律）
- [x] 4.4 验证崩溃重启：手动杀掉常驻进程，确认任务持有的 runner 自动拉起
- [x] 4.5 2026-09-18 事故修复：昨夜 17:57 注销后监控停止，今晨 10:28 登录触发 runner 静默死亡且 RestartOnFailure 未重试（空窗约 17 小时，杀进程复现确认 RestartOnFailure 对 runner 级死亡不生效）。修复：runner 主体加 try/catch 致命留痕（`=== runner fatal ... ===` 写当日 scan 日志后 exit 1）；注册脚本新增周期性看门狗触发器（`-WatchdogMinutes`，默认 5 分钟，IgnoreNew 下运行中为空操作）。已重新注册并通过「杀 runner+python → 看门狗下一周期自动拉起」实测

## 5. C2 hook 快速通道（已关闭：2.2 spike 一票否决，指令路径保持 k2.6 LLM 处理）

- [x] 5.1 ~~实现 `scripts/ff_command.py <开始|暂停|状态|写入|放弃>`~~（不适用：spike 否决）
- [x] 5.2 ~~实现 `hooks/wecom-command-fastpath/`（HOOK.md + handler.js）~~（不适用：spike 否决）
- [x] 5.3 ~~注册并启用 hook，逐条回归五指令~~（不适用：spike 否决）

## 6. C3 会话卫生

- [x] 6.1 新增 `scripts/register-session-compact.ps1`：注册每日一次的 Windows 计划任务，经 gateway 对 main agent 最近活跃的 wecom 群会话执行 `openclaw sessions compact`；gateway 离线时跳过并留痕 `logs/intranet-notify/`（stage `session-compact`），不发群消息
- [x] 6.2 手动触发一次验证：compact 成功、留痕正确、群会话不被重置

## 7. SKILL.md 与需求切换

- [x] 7.1 `skills/intranet-message-triage/SKILL.md`：「采集需求」块 `scanIntervalMinutes` 改为 `scanIntervalSeconds`（值 5）；「需求同步」「发送方式」等章节措辞同步（计划任务→常驻守护任务；指令由 hook 优先处理的说明，若第 5 组已实施）
- [ ] 7.2 走一遍需求确认闸端到端验证：需求同步发出确认消息 → 群内 @FF「开始」→ config 与常驻任务同步为新间隔 → 台账状态正确（现状：台账已有 2026-09-17 17:45 生成的 req-targets/req-versions/req-scan-interval=5 三条「待确认」，确认消息是否送达群内未核实；兜底 cron 因 Kimi 周配额耗尽被停用，需先启动 gateway 并 `openclaw cron enable intranet-message-notify` 才能续跑）

## 8. 收尾

- [x] 8.1 更新 `AGENTS.md` 发送渠道现状段（常驻模式、模型、hook、会话压缩）
- [x] 8.2 更新 `docs/intranet-file-monitor.md` 与 `wiki/log.md`（架构变化与实施记录）
- [x] 8.3 `openspec validate optimize-monitor-latency --strict` 通过
