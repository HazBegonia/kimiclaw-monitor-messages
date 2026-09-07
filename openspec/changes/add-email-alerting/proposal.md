# Proposal: add-email-alerting

## Why

内网监控链路（OpenClaw cron → `intranet_filename_monitor.py` → diff/focus/error 日志）已经在产出消息，但没有任何外发通道，告警只躺在本地日志里。企业微信推送的三条路目前都不可用：群机器人被企业管理员关闭、智能机器人长连接与自建应用均需管理员审批。按 AGENTS.md 最新决定：在企微通道恢复前，先用 SMTP 邮件把告警送到 `26213050235@m.fudan.edu.cn`（复旦邮箱，企微"邮件"页签可收），让告警链路先端到端跑起来。

## What Changes

- 新增邮件告警发送器：通过 QQ 邮箱 SMTP（`smtp.qq.com:465` SSL，发件账号 `852285268@qq.com`）把监控消息投递到指定收件邮箱。
- 版本变动消息整合：每次扫描产生的 diff/focus 日志汇总为一封邮件（增删文件清单 + 日志路径），避免一变动一封的碎片轰炸。
- 监控异常消息聚合：错误 JSONL 按 `errorType + phase` 聚合，一封邮件列出次数与时间范围（例如 "TimeoutError ×34（11:09–11:18）"），而不是逐条转发。
- 增量发送与去重：用状态文件记录已发送位置，同一日志内容不重复投递。
- 凭据外置：SMTP 授权码放在 `config/smtp.local.json`，加入 `.gitignore`，不进版本库。
- 发送动作挂到现有 `scripts/run-intranet-monitor.ps1` 单次扫描之后，不新增调度入口。
- 出口可插拔预留：发送接口与"邮件"实现解耦，企微通道（群机器人 webhook / 自建应用）获批后可作为新出口替换，不改核心逻辑。

## Capabilities

### New Capabilities

- `email-alerting`: 监控消息的邮件整合与投递——版本变动汇总邮件、异常聚合邮件、增量去重、SMTP 凭据与收件人配置、发送失败处理。

### Modified Capabilities

（无——现有内网监控行为不变，仅在其后追加发送环节。）

## Impact

- **新增代码**：`src/` 下邮件发送模块（SMTP、模板、聚合、去重状态）及对应测试。
- **修改**：`scripts/run-intranet-monitor.ps1`（扫描后追加发送步骤）、`.gitignore`（排除凭据文件）、`docs/workflow.md`（更新告警链路说明）。
- **新增配置**：`config/smtp.local.json`（凭据，本地文件不入库）及其示例模板。
- **依赖**：仅 Python 标准库（`smtplib`/`email`），无新增第三方包。
- **外部依赖**：QQ 邮箱需开启 SMTP 授权码；收件方（复旦邮箱）建议将发件地址加白名单防误判垃圾邮件。
- **后续**：企微群机器人/自建应用获批后，以新出口替换邮件出口（另开 change）。
