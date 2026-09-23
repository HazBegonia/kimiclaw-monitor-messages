# 企微智能机器人长连接独占：单 FF 错峰共用方案

> 2026-09-22 记录并实测。结论：监控推送（py 通知器）与 Claw 需求交互**共用同一个 FF 机器人**，靠「py 按需连接 + 发完立刻拉活 Claw」的编排错峰使用，互不常驻。

## 核心规则

企业微信服务端对同一个智能机器人（同一 botId）**同一时刻只接受一条长连接**（`wss://openws.work.weixin.qq.com`）。谁拿着该 botId 的 Bot ID/Secret 新连上来，服务器立刻把之前那条连接掐断（被踢方收到 `disconnected_event`）。没有排队、没有共享。

## 现行决议（2026-09-22 起，change: share-ff-bot-connection）

**单 FF 错峰共用**：FF 的长连接平时归 Claw 的 wecom 插件（守着等上级 @它提需求）；py 通知器有重要消息要发时，按以下编排短暂借线：

1. py 建连前先在 `state/bot-tool-state.json` 记一笔 `pendingRestore` 欠账（崩溃保险）；
2. py 连接 → **服务器踢下 Claw** → py 发推送 → py 主动断开；
3. py 立刻执行拉活：`openclaw config set channels.wecom.enabled --json false` 再 `true`，触发 gateway 热重载，Claw 的 wecom 插件重启通道、数秒内重新持线；
4. 若拉活失败（gateway 不可达等），欠账留账，通知器常驻循环每轮先调 `ensure_companion_alive()` 补拉活。

全部编排在 py 侧 `src/bot_tool.py`（可扩展工具层，预留 `dump_inbox()` 与多渠道注册点），不改腾讯插件。发送失败走 5s→30s→5m 退避（持久化在账本里）。

### 为什么必须靠 config 热重载拉活

腾讯 wecom 插件被踢后**故意永久挂起**（源码注释：被顶意味着别处有意接管，自动重连会造成互踢循环），只能靠外部触发 config reload 恢复。实测拉活全程（py 断开 → Claw 重新认证成功）约 27 秒，其中包含 3 秒宽限与两次 config 写入。

## 实测记录（2026-09-22 踢线演练）

- **推送链路**：Claw 持线状态下 `bot_tool.push_markdown()` 实发成功；Claw 被踢（`disconnected_event`）→ 27 秒内被 config 热重载拉活（`Authentication successful`），无互踢循环。
- **Kimi 桥（kimi-claw 桌面端通道）**：热重载只重启 wecom 通道，桥接 subscribe 连接无断连、无续订异常。
- **窗口消息不补发（关键结论）**：py 占线 90 秒期间上级发的 `@FF hi` 被推到 **py 的连接**上（py 只发不收，消息进黑洞）；Claw 重连后服务器**不补发**，该消息对 Claw 永久丢失。
- **踢线瞬间的半截消息**：Claw 被踢前一刻收到的消息，agent 处理完要回复时连接已断，回复发送失败（`WSClient not connected`）——群里表现为上级 @FF 无回应。

## 已接受的代价

- **推送窗口（每天 0~6 次 × 约 30 秒）内 @FF 的消息会丢**：窗口内消息只推给当时的持线者（py），py 丢弃，服务器不补发。上级若发现 @FF 无回应，重发即可（人工兜底）。
- 窗口期 Claw 对群内消息无感知、无回应。

## 历史背景：为什么以前一个 FF 就够

OpenClaw 时代（2026-09-18 之前）所有推送都经 gateway 里的 wecom 插件发出，FF 长连接只有一个主人（gateway）。2026-09-18 退役改造后，推送改由 py 通知器**自己直连**，从此出现两个连接主人，独占规则才开始咬人。

## 被否决的替代方案

- **建第二个智能机器人**（专职需求交互，Claw 独占；FF 专职推送）：最干净的隔离，但需要额外建/维护一个机器人，用户决定不建，接受单 FF 错峰。
- **推送改走 gateway 代发**（通知器调本机 gateway API，由 Claw 的 wecom 插件经 FF 发出）：一个机器人是省下了，但监控推送重新依赖 gateway 常驻——gateway 一挂，连「gateway 挂了」这条告警本身都发不出去，等于退回 9/18 改造前的结构性缺陷。
- **py 被踢后等 30 秒再重连（被动等 Claw 回来）**：不必要的延迟——py 发完主动断开的那一刻线已空，立刻拉活即可，无需等待。
- **不管不顾直接共用**（无拉活编排）：Claw 被踢后永久挂起，需求入口常断，不可行。

## 未来扩展位

py 占线期间实测能收到 `aibot_msg_callback`（含消息正文与发送者），`src/bot_tool.py` 已预留 `dump_inbox()` 空实现——将来如需消除窗口消息丢失，可在占线期间把收到的消息落盘，拉活后转交 Claw 处理。
