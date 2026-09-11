# Design: wecom-aibot-notify

## Context

现状与动机见 proposal.md。对设计有直接影响的事实：

- OpenClaw gateway 本机常驻（2026.7.1，Kimi key 主链路可用），已有 cron 体系驱动 `scripts/run-intranet-monitor.ps1` 单次扫描；监控产物为 `logs/intranet-diff/`（变更）与 `logs/intranet-error/YYYY-MM-DD.log`（错误，JSONL）。
- 发送端凭证：智能机器人 FF，Bot ID / Secret 已有（仅存于全局 `~/.openclaw/openclaw.json`，本文档不落明文）；目标为测试企业「未命名企业」全员群（成员：李非凡 + FF BOT）。
- 长连接协议要点（官方文档 path/101463）：端点 `wss://openws.work.weixin.qq.com`；`aibot_send_msg` 支持主动推送 markdown/模板卡片；**前置条件是目标会话中须有用户先与机器人交互**；每会话频控 30 条/分钟、1000 条/小时；同一机器人同时只能持有一条长连接。

## Goals / Non-Goals

**Goals:**
- flow1/flow2 的重要消息实时推送到全员群，李非凡手机端可收。
- 复用现有 cron + claw 链路，不新增常驻进程。
- 密钥只进 OpenClaw 全局配置，仓库零明文密钥。

**Non-Goals:**
- 不做群内人机对话功能（@FF 聊天由插件默认能力承载，非本变更目标）。
- 不接钉钉、不接个人微信、不接邮件通道。
- 不动现有扫描器、快照与错误日志行为。
- 不解决真实生产企业的审批/部署问题（测试企业先行验证）。

## Decisions

### D1：用官方插件 `@wecom/wecom-openclaw-plugin`，而非自研 SDK 守护进程

gateway 本就常驻，插件以渠道形式持有长连接，天然满足"出站连接、无公网入口"约束，且官方维护、带 Pairing 鉴权流程。备选方案对比：

| 方案 | 结论 | 理由 |
|---|---|---|
| 官方 OpenClaw 插件 | **采用** | gateway 常驻持有连接；零新进程；官方支持 |
| Python `aibot-python-sdk` 自研发件箱守护进程 | 回退方案 | 多一个常驻进程与守护问题，违背项目"cron 单次扫描、无常驻"的现状；仅当插件主动推送能力不满足时启用 |
| 自建应用 message/send | 放弃 | 可信IP 前置要求（可信域名/回调URL）无法满足 |
| 经典 webhook 群机器人 | 放弃 | 新版客户端创建入口已导向智能机器人；且 webhook 机器人在真实企业需审批 |

### D2：发送动作由 claw 在 cron 流程内完成，不做独立发送进程

cron 唤醒 → 扫描 → claw 读日志 → triage 判定 → 通过企微渠道 push。判定与发送在同一轮 agent 会话内串行完成，产物仍是本地日志，链路可断点排查。

### D3：chatid 存项目配置、Secret 只进全局配置

- `config/wecom-aibot.json`：存 `chatid`、目标群名称等脱敏配置，允许入库。
- Bot ID/Secret：仅经 `openclaw channels add` 写入全局 `~/.openclaw/openclaw.json`；项目文档与脚本只引用渠道名。

### D4：每轮聚合为一条 markdown 推送

单轮扫描的全部重要变更/错误聚合成一条 markdown（标题 + 时间 + 文件列表/错误摘要 + 内网链接），规避频控并减少打扰。群机器人 markdown 在部分客户端渲染受限，若显示异常则降级为纯文本分段——属实施期微调，不改规格。

### D5：triage 规则初稿内嵌 skill，后续可调

`.agents/skills/intranet-message-triage/SKILL.md` 补全判定规则初稿：新增/删除 `.csv` = 重要；监控器自身错误（页面校验失败、持久化失败、连续拉取失败）= 重要；无变化 = 不发送。规则由公司上级最终界定，skill 文本即调参入口。

## Risks / Trade-offs

- [官方插件的"主动推送到指定 chatid"调用方式未经本机验证] → 实施第一步先冒烟：渠道上线后直接 push 一条测试消息，失败则立即转回退方案（D1），不动其余部分
- [机器人使用模式为「仅个人使用」，群推送可能权限不足] → 实施时若报权限错误，将机器人改为企业内可用/重新授权「消息」权限后重试
- [长连接单点：gateway 重启/掉线期间推送中断] → 推送失败写本地日志（规格要求），恢复后可在日志中追溯漏发；分钟级监控可接受
- [Secret 已在聊天中明文出现] → 链路验证通过后，由用户在机器人设置页重置 Secret 并更新渠道配置
- [「激活会话」前置条件被意外重置（如机器人被移出群再加回）导致推送失败] → 文档中记录恢复步骤：重新 @FF 发一条消息并确认 chatid 配置

## Migration Plan

1. 安装插件、配置渠道、Pairing 配对（凭证入全局配置）。
2. 群内 @FF 激活会话，解析 chatid 写入 `config/wecom-aibot.json`。
3. 冒烟推送测试消息，李非凡确认收到。
4. 接入 cron 链路（triage + 发送），端到端验证 flow1/flow2。
5. 更新文档（workflow.md、intranet-file-monitor.md、AGENTS.md、wiki）。

回滚：`openclaw channels remove` 删除企微渠道（可再 `openclaw plugins uninstall`），删除 `config/wecom-aibot.json`，文档改回；监控扫描本身全程不受影响。

## Open Questions

- 官方插件在 cron 触发的 agent 会话中执行主动推送的确切指令形态（channel 目标寻址格式）——实施时以插件 README/`openclaw channels` 提示为准，不影响规格与任务拆分。
