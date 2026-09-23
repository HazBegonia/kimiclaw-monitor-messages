# Proposal: wecom-aibot-notify

## Why

内网监控（cron + Python 扫描）目前只把变化写进本地日志，flow1/flow2 的最后一段"筛选重要消息 → 发送到企业微信"尚未落地，李非凡无法实时收到告警。

自建应用路线被卡死：配置企业可信IP 前必须先设置"可信域名"或"接收消息服务器URL"，两者都需要与备案主体关联的公网域名/入口，测试企业没有。企业微信**智能机器人（长连接模式）**由客户端主动外连 `wss://openws.work.weixin.qq.com`，不需要域名备案、不需要可信IP，且有官方 OpenClaw 插件（`@wecom/wecom-openclaw-plugin`），与本项目"OpenClaw + Kimi key"的最小尝试路线完全吻合。

## What Changes

- 安装并配置 `@wecom/wecom-openclaw-plugin`，用智能机器人 FF 的 Bot ID + Secret 在 OpenClaw gateway 中建立企业微信渠道（长连接，由常驻 gateway 持有）。
- 在测试企业「未命名企业」全员群激活会话（成员 @FF 发一条消息），从渠道回调获取群 `chatid` 并持久化到项目配置（脱敏）。
- 补全占位的 `intranet-message-triage` skill：定义重要性判定规则初稿，把同一轮扫描的多条变化/错误聚合成一条 markdown 告警文本。
- 在现有 cron 链路中接入"判定 → 发送"：flow1 读 `logs/intranet-diff/`，flow2 读 `logs/intranet-error/`，重要消息经企微渠道主动推送（`aibot_send_msg`）到全员群。
- 更新 `docs/workflow.md`、`docs/intranet-file-monitor.md`、`AGENTS.md` 与 wiki，记录新链路。
- 现有扫描、快照、错误日志行为不变（无 BREAKING）。

## Capabilities

### New Capabilities

- `wecom-aibot-notify`: 通过企业微信智能机器人长连接渠道，将 triage 判定为重要的监控消息（文件变更、监控错误）主动推送到指定群会话；涵盖渠道配置、会话激活、消息聚合与频控约束。

### Modified Capabilities

（无——现有 `intranet-error-logging`、`configurable-version-snapshot-logs` 的需求不变。）

## Impact

- **新增依赖**：`@wecom/wecom-openclaw-plugin`（OpenClaw 官方插件，装入全局 `~/.openclaw`，属"全局配置除外"条款）。
- **配置**：Bot ID / Secret 仅存于全局 `~/.openclaw/openclaw.json`；项目内只保存脱敏引用与群 `chatid`，不引入明文密钥。
- **代码/文档**：`.agents/skills/intranet-message-triage/SKILL.md`（补全）、`docs/workflow.md`、`docs/intranet-file-monitor.md`、`AGENTS.md`、`wiki/`。
- **外部约束**：企微推送频控 30 条/分钟、1000 条/小时/会话；机器人同时只能持有一条长连接；主动推送前必须有人在目标会话中与机器人交互过。
- **风险**：官方插件主动推送能力若不足，回退方案为 Python 常驻小进程（官方 `aibot-python-sdk` 持有长连接 + 扫描 `state/wecom-outbox/` 发件箱），详见 design.md。
