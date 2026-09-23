## Context

现状实测：py 单次扫描 1~2 秒（fetch 320ms），瓶颈在调度与唤醒。计划任务每分钟 tick（Windows 下限）；事件唤醒用 `openclaw agent --local`（嵌入式冷启动）；全部 agent 会话跑 `kimi-coding/k3-256k`，一次 triage 会话实测约 112 秒。群会话长存，历史只增不减。py 脚本自带常驻模式（`--interval` 秒级轮询、每轮热读 config），`run-intranet-monitor.ps1 -Mode Start` 已具备入口。

约束：OpenClaw 全局配置在 `~/.openclaw/`（允许动）；其余产物一律在项目根目录内。bundled hook 先例 `weixin-contact-monitor`（监听 `message:received`，handler 为本地 js）。

## Goals / Non-Goals

**Goals:**
- 检测延迟：平均 30s → ≤5s（常驻 5s 轮询）。
- agent 全链路提速：main agent 默认模型切到 `kimi-coding/kimi-k2.6`。
- 五控制指令确定性秒回（hook 快速通道，spike 验证可行性）。
- 群会话历史每日压缩，抑制响应劣化。

**Non-Goals:**
- 不改唤醒链的 `--local` 机制（上一轮讨论未选 B1，仍由 k2.6 提速兜底）。
- 不改 triage 判定规则与推送模板、不动 wecom 插件配置。
- hook 只处理五个指令，自然语言草案/查询仍走 LLM。

## Decisions

**D1：常驻进程由「守护计划任务」承载，注册脚本从 schtasks 切到 Register-ScheduledTask。**
守护任务需要「登录触发 + 失败自动重启 + 单实例策略」，schtasks CLI 表达不了 RestartCount/RestartInterval 与 MultipleInstancesPolicy，改用 PowerShell 原生 cmdlet。隐藏窗口沿用已验证的 `conhost.exe --headless`。每分钟 tick 旧任务按单调度器铁律迁移：先注册验证新任务，再删旧任务。

2026-09-18 事故补充：RestartOnFailure 在 runner 进程死亡（任务实例非正常结束）时实测不触发重试（杀进程与今晨登录启动失败两次均未重试，任务 XML 配置确认无误）。因此在登录触发器之外增加周期性看门狗触发器（默认 5 分钟，注册脚本 `-WatchdogMinutes` 可调）：运行中因 IgnoreNew 为空操作，任务死亡后在下一周期自动拉起。runner 自身另加 try/catch 兜底，致命异常写入当日 scan 日志后 exit 1，杜绝静默死亡。

**D2：单实例双保险——任务级 IgnoreNew + py 侧心跳锁。**
计划任务层 `MultipleInstancesPolicy=IgnoreNew` 挡住任务计划重复触发；py 常驻循环启动时原子创建 `state/monitor-resident.lock`（含 PID 与心跳时间戳，每轮刷新），发现活锁立即安静退出；锁超过 2 个轮询周期未刷新视为死锁可接管。防的是手动双开与守护任务叠加。

**D3：暂停语义落到 config——空 targets = 空转，不报错。**
`load_monitors_config` 目前对空 targets 抛错，常驻模式下会每 5 秒刷错误日志。改为：文件存在且 `targets` 为合法空数组 → 本轮安静跳过；文件缺失/损坏 → 仍是 `read_config` 错误。一次性模式（`--once`）行为不变，避免影响既有测试与回滚路径。

**D4：轮询间隔走 CLI 参数重启生效，不追求热更。**
interval 是进程级参数，热更新复杂度不值。需求激活 `scanIntervalSeconds` 时，注册脚本重建守护任务并 `schtasks /end` + `/run` 重启常驻进程；targets/versions 变更仍靠每轮热读 config 自动生效。`scanIntervalMinutes` 旧字段忽略（spec 已声明）。

**D5：kimi-k2.6 先验证后切换，一处配置全链路生效。**
向 provider `kimi-coding` 的 models 列表注册 `kimi-k2.6`，用一条 `openclaw agent --local --model kimi-coding/kimi-k2.6` 测试消息验证可用；通过后改 `agents.defaults.model.primary`。验证失败则保持 k3-256k 并回报，不硬切。回滚就是改回一行。

**D6：C2 spike 先行，两个判定问题一票否决。**
先读 `weixin-contact-monitor` 的 HOOK.md/handler.js 摸清 API，回答：(1) handler 能否阻止消息继续进入 agent 会话（吞掉）；(2) handler 能否主动向企微群回复。任一答案为否 → 放弃 hook 路线，指令仍由 k2.6 驱动的 LLM 会话处理，本项记为未实施。
若可行：hook 源码放项目内 `hooks/wecom-command-fastpath/`，指令逻辑收敛到一个确定性脚本 `scripts/ff_command.py <指令>`（操作台账/草案/config + 输出回复文本），hook handler 只做匹配与调用，LLM 兜底路径语义不变。SKILL.md 相应章节注明「指令由 hook 优先处理」。

**D7：C3 用 `openclaw sessions compact` 走 gateway，绝不碰会话文件。**
此前手工重置会话踩过文件锁的坑；compact 子命令经运行中的 gateway 操作，天然避开。新注册脚本 `scripts/register-session-compact.ps1` 创建每日任务：解析 main agent 最近活跃的 wecom group 会话 → compact → 留痕 `logs/intranet-notify/`（stage `session-compact`）；gateway 离线则跳过留痕，不告警。

## Risks / Trade-offs

- kimi-k2.6 在 provider 上不存在或未开通 → D5 验证闸，失败保持现状并回报。
- 小模型 triage 误判率上升（漏报/吵人）→ 判定规则高度结构化，风险可控；观察一周，不行一行回滚。
- hook 吞不掉消息会导致「脚本回一遍、LLM 再回一遍」→ D6 spike 一票否决，不带伤上线。
- hook 指令逻辑与 SKILL.md 的 LLM 路径语义可能漂移 → 指令操作收敛进 `scripts/ff_command.py` 单一实现；SKILL.md 声明 hook 优先，LLM 路径仅在 hook 缺席时启用。
- 机器重启后无人登录则常驻扫描不启动 → 任务同时注册 logon 触发；本机为日常办公机，风险可接受，记录在案。
- 常驻进程日志持续增长 → 沿用现有按日滚动 + 错误日志 30 天/100MB 保留策略，不新增负担。

## Migration Plan

1. 验证并切换模型 kimi-k2.6（独立、可立即回滚）。
2. C2 spike（只读调查，无线上影响）。
3. py 常驻化改造（锁、空转）+ 单测 → 注册守护任务并验证 → 删除每分钟 tick 旧任务。
4. SKILL.md「采集需求」块改 `scanIntervalSeconds` —— 这会触发既有的需求确认闸：改完后走一遍「@FF 开始」激活，顺带端到端验证新链路。
5. 注册每日会话压缩任务。
6. spike 通过则实施 hook 快速通道并回归五指令；不通过则本项关闭。
