# Proposal: share-ff-bot-connection

## Why

上级需求变更要经企微群 @机器人直达 Kimi Claw（OpenClaw-oRz 已完成关联），而 Claw 的 wecom 插件需要 24h 持有长连接收消息；现有 py 通知器推送也要用同一 FF 机器人的长连接。企微服务端对同一 botId 只认一条连接（新连踢旧连），且源码证实腾讯 wecom 插件被踢后**故意永久挂起、绝不自动重连**（防互踢设计）。决策已定：不新建第二个机器人，单 FF 共用——因此需要一套 py 侧的错峰与拉活编排，让推送与需求交互互不伤害。

## What Changes

- 新增 `src/bot_tool.py`：bot 工具层（门面），封装高层推送接口与全部连接编排——按需连接、发送、断开、**发完立刻拉活 Claw**（`openclaw config set channels.wecom.enabled` false→true 触发 gateway 热重载恢复通道）、发送失败指数退避（5s→30s→5m 封顶）、「Claw 待拉活」欠账账本（`state/bot-tool-state.json`）。预留 inbox 落盘与钉钉/邮件等渠道扩展位。
- 修改 `src/intranet_notifier.py`：推送路径改为调用 `bot_tool.push_markdown()`；常驻循环每轮调用 `bot_tool.ensure_companion_alive()` 兜底拉活（推送中途崩溃也不致 Claw 永久下线）。
- 修改 `src/wecom_bot_client.py`：无协议变更；仅配合工具层需要的少量接口整理（如连接事件回调），保持 0-token 按需连接语义。
- 全局配置 `~/.openclaw/openclaw.json`：`channels.wecom.enabled` 由 false 恢复为 true（FF 凭证交给 Claw 的 wecom 插件常驻持有）。
- gateway 常驻化：注册 Windows 计划任务运行 `openclaw gateway run`（当前为会话内临时进程，会话结束即死，拉活动作依赖 gateway 存活）。
- 更新 wiki 文档 `wiki/wecom-bot-connection-exclusivity.md` 的「现行决议」节为单 FF 共用方案。

## Capabilities

### New Capabilities

- `wecom-bot-tool`: 企微 bot 工具层——对调用方暴露高层推送接口，内部封装按需连接发送、踢线后拉活 Claw 的编排、发送失败退避与欠账保险；同层可扩展收件箱落盘与钉钉/邮件等新渠道，调用方（通知器及未来脚本）不接触协议细节。

### Modified Capabilities

- `wecom-aibot-ws-client`: 「连接独占约束」修订为「错峰共用」——同一 FF 凭证允许通知器（按需短时连接）与 Claw wecom 插件（常驻）共用，由工具层编排保证同一时刻只一方持有连接，且通知器使用完毕后必须恢复对方连接。
- `py-notifier-loop`: 推送动作改经 bot 工具层完成；发送失败重试由「下轮立即重试」修订为「指数退避重试」，且每轮需先履行欠账拉活检查。

## Impact

- **代码**：新增 `src/bot_tool.py`；修改 `src/intranet_notifier.py`、`src/wecom_bot_client.py`（小幅）；新增 `tests/test_bot_tool.py`、更新 `tests/test_intranet_notifier.py`。
- **状态**：新增 `state/bot-tool-state.json`（欠账与退避账本）；`state/notify-state.json` 游标语义不变。
- **全局配置**：`~/.openclaw/openclaw.json` 的 `channels.wecom.enabled` 恢复 true（仓库外，手工/脚本执行）。
- **运维**：新增 gateway 常驻计划任务；新增踢线演练（验证 toggle 拉活、热重载对 Kimi 桥影响、窗口消息补发行为）。
- **不改腾讯插件**：`@wecom/wecom-openclaw-plugin` 保持原样，升级不受影响。
- **已接受的代价**：推送窗口（每次几秒，每天 0~6 次）内 @FF 的消息会丢；上级追问即人工兜底。
