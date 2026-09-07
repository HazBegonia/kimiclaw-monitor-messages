# Design: add-email-alerting

## Context

现有链路：OpenClaw cron → `scripts/run-intranet-monitor.ps1` → `src/intranet_filename_monitor.py`（单次扫描），产出三类日志：`logs/intranet-diff/`（通用变动）、`logs/intranet-focus/<version>/`（版本快照）、`logs/intranet-error/YYYY-MM-DD.log`（错误 JSONL，append-only）。monitor 脚本已有"失败落盘重试"模式（`state/openclaw-pending` outbox）可参考。约束：仅用 Python 标准库；本机文件全部放项目目录；ps1 脚本须 UTF-8 with BOM 保存。

## Goals / Non-Goals

**Goals:**

- 扫描结束后自动把新产生的变动/异常整合成邮件发出，端到端可验证（发测试邮件）
- 聚合控量、游标去重、失败重试不拖垮监控
- 出口可插拔：邮件是首个实现，企微通道获批后低成本替换

**Non-Goals:**

- 不做消息重要性 triage（`skills/intranet-message-triage` 占位，另开 change 接入）
- 不发"一切正常"心跳邮件；不做 HTML 富文本邮件
- 不改动 `intranet_filename_monitor.py` 的监控与日志行为
- 不实现企微出口（群机器人/自建应用待审批）

## Decisions

### 1. 发送器为独立模块，不塞进 monitor 脚本

新增 `src/email_notifier.py`，可独立运行（`python -m src.email_notifier`），由 `run-intranet-monitor.ps1` 在 monitor 调用之后追加调用。理由：职责分离——monitor 只负责"监控+落盘"，sender 只负责"读日志+外发"；可独立测试、独立重跑、独立降级。替代方案（内嵌进 monitor）会耦合两类错误语义，拒绝。

### 2. 增量去重用游标状态文件，不用消息队列

`state/notify-state.json` 记录：diff/focus 已发送到的最新日志文件名（文件名含时间戳，字典序即时间序），error JSONL 的 `(日期, 字节偏移)`。字节偏移对 append-only JSONL 简单可靠。替代方案（每条待发送复制进 outbox 目录）会重复存储日志内容，游标足够，拒绝。状态文件缺失时以"当前最新位置"为基线（见 specs 增量去重要求）。

### 3. 聚合在发送时做，cron 周期即天然窗口

error 按 `(errorType, phase)` 分组：计数 + 首末时间 + 首条 message 示例；version 变动把本批全部条目合并成一封。不做跨周期滑动窗口抑制——cron 间隔（分钟级）本身就是聚合窗口，现阶段够用。

### 4. 纯文本 UTF-8 邮件，SMTP_SSL:465

`smtplib.SMTP_SSL("smtp.qq.com", 465)`；主题含中文用 RFC 2047 编码（`email.header.Header`）；正文 `MIMEText(..., "plain", "utf-8")`。复旦邮箱对纯文本兼容最好，实现也最简单。

### 5. 可插拔出口只留接缝，不建插件框架

内部接口约定 `send(subject: str, body: str) -> None`；配置文件预留 `channel` 字段（当前恒为 `"email"`）。未来企微 webhook/自建应用作为同一接口的新实现替换。不做抽象基类/注册表等完整框架（YAGNI）。

### 6. 凭据外置：`config/smtp.local.json` + 示例模板

字段：`host / port / username / auth_code / from / to[]`。`.gitignore` 增加 `*.local.json`；入库 `config/smtp.local.example.json` 作模板。文件缺失或字段不全 → 打印提示并跳过发送（exit 0），不影响 ps1 主流程。

### 7. 失败语义：不推进游标，下次 cron 自然重试

发送抛异常 → 控制台输出原因、游标保持不动、进程正常退出。失败不重试当场死等；也不写入 monitor 的 error log（那是"监控目标"的错误语义，不混淆）。cron 周期到来时自然重发。

## Risks / Trade-offs

- QQ → 复旦邮箱被判垃圾邮件 → 测试邮件到达后收件方加白名单；workflow.md 写明此步骤
- 授权码泄露 → 凭据文件 gitignore；文档提醒不要外发
- QQ SMTP 日发送上限 → 聚合已把量级压到很低；超限表现为发送失败，下次 cron 重试
- 长时间发送失败导致积压，单封邮件过大 → 正文明细截断（如前 50 条 + "另有 N 条，见日志目录"）
- 本机 465 端口出站被防火墙拦 → 降级为跳过发送，监控不受影响；首次测试邮件即验证此项

## Migration Plan

纯新增能力，无数据迁移。部署 = 建配置文件 + ps1 追加一行调用；回滚 = 移除该行调用，monitor 行为完全不变。

## Open Questions

- 企微通道获批后的出口替换方案（另开 change 设计）
- 是否需要抄送多人（`to` 已是数组结构，届时加地址即可）
