## Why

当前监控链路端到端延迟 1.5~3 分钟，实测瓶颈有三处：Windows 计划任务最小粒度 1 分钟导致检测平均滞后 30 秒；事件唤醒走 `openclaw agent --local` 冷启动嵌入式运行时；triage 与 @FF 交互全部跑 `k3-256k` 大模型，一次 triage 会话实测约 1 分 52 秒。py 脚本本身只需 1~2 秒，不是瓶颈。同时群会话历史只增不减，响应随时间进一步变慢。

## What Changes

- **扫描常驻化**：py 脚本改用其自带的常驻模式（5 秒轮询，config 每轮热读），由「登录触发 + 崩溃自动重启 + 隐藏窗口」的 Windows 计划任务承载，替换现有的每分钟 tick 任务；加单实例保护；需求暂停时常驻循环安静空转，不刷错误日志。
- **扫描间隔语义调整**：「采集需求」的 `scanIntervalMinutes`（分钟，计划任务粒度）调整为 `scanIntervalSeconds`（秒，常驻轮询粒度），缺省 5 秒。
- **模型切换**：OpenClaw main agent 默认模型从 `kimi-coding/k3-256k` 切换为 `kimi-coding/kimi-k2.6`（需先在 provider 注册并验证可用性），triage 唤醒、兜底轮、@FF 交互全链路生效。
- **指令快速通道（C2，已否决）**：原计划自研 `message:received` hook 对五个控制指令做确定性脚本处理。2026-09-16 spike 依据官方文档一票否决：内部 hook 是副作用观察器，无 block/cancel 语义，且 `message:*` 事件不向 `event.messages` 投递，无法经 hook 回复群。五指令保持 k2.6 驱动的 LLM 会话处理，本项未实施。
- **会话卫生（C3）**：新增每日一次的 Windows 计划任务，通过 `openclaw sessions compact`（走运行中的 gateway，无文件锁问题）压缩 @FF 群会话，抑制历史膨胀导致的响应劣化。

## Capabilities

### New Capabilities

- `wecom-session-hygiene`: @FF 群会话的定期压缩维护——每日经 gateway 对群会话执行 compact，抑制历史膨胀；执行失败时留痕不告警轰炸。

### Modified Capabilities

- `system-scheduled-scan`: 调度载体从「每分钟触发的计划任务」变为「登录触发、崩溃重启的常驻进程守护任务」；扫描粒度从分钟级变为秒级；新增单实例保护与暂停空转要求。
- `skill-driven-requirement-lifecycle`: 扫描间隔需求字段从 `scanIntervalMinutes` 变为 `scanIntervalSeconds`（缺省 5 秒），需求同步的派生目标从「计划任务间隔」变为「常驻进程轮询间隔」。

（`wecom-bot-control-commands` 原计划新增 hook 快速通道，spike 否决后无变更。）

## Impact

- **代码**：`src/intranet_filename_monitor.py`（单实例保护、暂停空转、resident 细节）、`scripts/run-intranet-monitor.ps1`、`scripts/register-windows-scheduler.ps1`（或新增 resident 注册脚本）、新增会话压缩计划任务脚本。~~新增 hook handler~~（spike 否决，未实施）。
- **配置**：`~/.openclaw/openclaw.json`（provider 注册 `kimi-k2.6`、默认模型切换）、`skills/intranet-message-triage/SKILL.md`（采集需求字段、发送与指令章节的措辞）。
- **规范**：上述三个 Modified 能力域的主 spec 需同步。
- **运维**：旧每分钟计划任务删除、新常驻守护任务注册、每日压缩任务注册；gateway 仍需常驻（compact 依赖 gateway）。
- **风险**：kimi-k2.6 模型可用性未验证（实施第一步验证）；hook 拦截/回复能力未证实（spike 任务）；常驻进程带来进程看护复杂度。
