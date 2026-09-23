# Design: share-ff-bot-connection

## Context

现状与约束（动机见 proposal.md）：

- `src/wecom_bot_client.py` 已实现 aibot 长连接协议（subscribe/send/req_id 回执/disconnected_event 感知），`src/intranet_notifier.py` 每 5 秒常驻轮询、按需直连推送，单实例由心跳锁保证。
- 腾讯插件 `@wecom/wecom-openclaw-plugin` 的 `disconnected_event` 处理器**故意永久挂起**（源码注释：reject/resolve 都会触发框架 auto-restart 形成互踢死循环）；同文件注释确认「用户修改配置 → config reload → stopChannel + startChannel → 正常恢复」。
- OpenClaw gateway（2026.7.1-2）当前以会话内临时进程运行，已关联 Kimi Claw；`channels.wecom` 已禁用待恢复。
- Windows 排障教训：py 侧 `subprocess` 调 openclaw 必须 `shutil.which` 解析到 `openclaw.cmd`（CreateProcess 不试 PATHEXT）。

## Goals / Non-Goals

**Goals:**
- 单 FF 凭证下推送与 Claw 常驻收消息错峰共存，同一时刻只一方持线
- 推送后立刻恢复 Claw 连接；推送进程崩溃也能兜底恢复
- 发送失败退避，杜绝踢线风暴
- 渠道与编排收敛进 `src/bot_tool.py`，调用方不接触协议细节

**Non-Goals:**
- 不改腾讯 wecom 插件与 openclaw 本体任何代码
- 不做推送窗口内的消息补偿（inbox 落盘仅预留扩展位，本期不实现）
- 不实现钉钉/邮件渠道（仅预留）
- 不动采集器 py1 与 triage 规则链路

## Decisions

### D1: 拉活动作 = `openclaw config set` toggle 触发热重载

发完推送、断开连接后，依次执行 `openclaw config set channels.wecom.enabled --json false` 与 `... true`。第一次写触发 stopChannel（通道本已挂起，空操作），第二次触发 startChannel 重连。选择理由：插件源码注释明确背书的恢复路径；CLI 官方接口，升级安全。备选：① 改插件 `disconnected_event` 处理器加定时重连——改 node_modules，升级即丢，否决；② gateway 整体 restart——连坐 Kimi 桥与全部通道，过重，否决；③ gateway 未文档化 RPC——脆弱，否决。

### D2: 拉活时机 = 发完立刻，不等 30 秒

30 秒等待只在「对端自行决定重连时机」的设想下需要（防反踢）。改为由工具层在自身断开连接后主动拉活，线上已空无一人，等待纯属浪费。对端离线窗口因此从 30s+ 缩到推送本身的几秒。

### D3: 欠账账本保证崩溃可恢复

每次建连前写 `state/bot-tool-state.json`：`pendingRestore: { kickedAt, dueAt }`；拉活成功即清除。`ensure_companion_alive()` 供常驻循环每轮调用：发现未清偿且到期（dueAt ≤ now，初始 dueAt≈kickedAt，留数秒余量）即执行 D1。崩溃情景下下一轮循环补拉活，对端不会永久下线。

### D4: 发送失败退避状态机

账本同文件记录 `sendBackoff: { failCount, nextRetryAt }`：失败按 5s→30s→5m 封顶倍增，成功清零。退避未到期时 `push_markdown` 直接返回退避中错误，不发起连接。状态持久化，进程重启不丢。

### D5: 工具层门面，协议层不动

`src/bot_tool.py` 只做编排，协议细节留在 `wecom_bot_client.py`。对外接口：`push_markdown(text) -> None|raise`、`ensure_companion_alive() -> None`。预留 `dump_inbox()` 与多渠道注册点。调用 openclaw CLI 统一走 `shutil.which("openclaw")` 解析，超时与返回码显式处理。

### D6: gateway 常驻化复用既有注册脚本

用 `scripts/register-windows-scheduler.ps1` 同款模式新增任务（如 `KimiclawOpenclawGateway`）：登录触发 + 守护触发器，runner 崩溃自拉起。与 py1/py2 任务同生命周期（锁屏照跑、注销停）。

## Risks / Trade-offs

- [推送窗口内 @FF 消息丢失（服务器大概率不补发）] → 已决策接受；量级每天 0~6 次 × 几秒；后续可在工具层 `dump_inbox()` 扩展位补偿
- [toggle 触发的整局热重载可能闪断 Kimi 桥] → 桥有 since_id 断点续订；踢线演练实测确认，若伤桥再改为更窄的恢复手段
- [gateway 死亡时拉活欠账积压] → `ensure_companion_alive()` 每轮重试；gateway 本身由守护触发器拉起；通知器推送主链路不依赖 gateway，互不影响
- [config set 双写期间被人工编辑 openclaw.json 冲突] → 两次写间隔 <1s；且该文件日常无人手改，风险可忽略
- [欠账账本损坏] → 读失败按空账本处理（宁多拉活一次，不错过拉活）

## Migration Plan

1. 实现 `bot_tool.py` + 改造 `intranet_notifier.py`，`pytest` 全绿（含新增 `tests/test_bot_tool.py`）
2. 注册 gateway 常驻计划任务并确认存活
3. `channels.wecom.enabled=true`，确认 Claw 持线收 @消息正常
4. 踢线演练：`python -m src.intranet_notifier --once` 实发 → 观察 Claw 被踢→数秒内被拉活→@消息恢复收发；检查 Kimi 桥日志无异常
5. 更新 `wiki/wecom-bot-connection-exclusivity.md`「现行决议」与 AGENTS.md 架构节
6. **回滚**：`channels.wecom.enabled=false` + 停 gateway 任务 → 回到通知器独占 FF 的现状；工具层拉活失败只记欠账，代码天然向后兼容

## Open Questions

- 被踢窗口内企微服务端是否补发消息（演练实测；影响是否启用 inbox 落盘扩展位）
- 热重载对 Kimi 桥的实际影响程度（演练观察日志）
