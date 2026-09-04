## Purpose

为内网网页提供可配置字段变化监控，在不访问后台源目录的前提下，以常驻轮询方式发现变化、记录本地日志，并为后续唤醒 OpenClaw 提供可靠事件。

## ADDED Requirements

### Requirement: Poll and parse configured webpage fields

系统 MUST 以常驻进程按可配置间隔请求目标网页，并从成功响应中提取配置声明的字段。默认配置 MUST 监控根目录下 CSV 链接组成的 `root_files` 集合；系统 MUST 不访问源目录或 CSV 正文。

#### Scenario: Successful field extraction
- **WHEN** 目标网页返回 HTTP 200 且页面结构通过校验
- **THEN** 系统提取并规范化配置字段，形成当前字段快照

#### Scenario: Configurable interval
- **WHEN** 启动参数指定 1 秒、5 秒或其他正数间隔
- **THEN** 系统按该间隔持续请求网页，而不是由 OpenClaw cron 重启 agent

### Requirement: Compare successful snapshots

系统 MUST 只将当前成功快照与最近一次成功快照比较。首次成功请求 MUST 只建立基线；字段无变化时 MUST 不生成日志且 MUST 不发送 OpenClaw 事件。

#### Scenario: Field changed
- **WHEN** 当前快照与基线在至少一个配置字段上不同
- **THEN** 系统记录变化前后值或集合差异，并生成一份本地 `.log` 文件

#### Scenario: Unchanged snapshot
- **WHEN** 当前快照与最近一次成功快照相同
- **THEN** 系统不创建日志、不更新变化事件、不调用 Kimi

### Requirement: Reject invalid responses without false removals

系统 MUST 将请求失败、非 HTML 响应、页面结构校验失败或不完整解析视为本轮失败。失败时 MUST 保留最近一次成功状态，不得把字段误判为消失。

#### Scenario: Request failure
- **WHEN** 请求超时、连接失败或返回非成功状态
- **THEN** 系统保留旧状态，不生成字段删除日志，并记录诊断信息

#### Scenario: Invalid or empty page
- **WHEN** 页面缺少预期签名、解析不完整或异常为空
- **THEN** 系统保留旧状态，不生成变化日志

### Requirement: Emit an OpenClaw wake-up event after durable logging

字段变化日志成功落盘后，系统 MUST 通过可配置事件接口为 OpenClaw 发送一次唤醒事件。事件至少 MUST 包含事件 ID、监控 ID、日志路径和检测时间；事件发送失败时 MUST 保留待投递记录并支持重试。系统 MUST 不在无变化轮询中调用 Kimi。

#### Scenario: Event delivery succeeds
- **WHEN** 变化日志已成功写入且 OpenClaw 事件接口返回成功
- **THEN** 系统记录事件已投递，并允许 OpenClaw 读取该日志进行后续处理

#### Scenario: Event delivery fails
- **WHEN** OpenClaw 事件接口不可达或返回失败
- **THEN** 系统保留待投递事件，后续使用同一事件 ID 重试，不丢失本地日志

### Requirement: Provide near-real-time semantics explicitly

系统 MUST 将监控能力标记为客户端轮询下的准实时。由于目标 HTTP 服务不提供 SSE、WebSocket、Webhook、ETag 或 Last-Modified，系统 MUST 不宣称服务器主动推送式严格实时。

#### Scenario: Detection latency
- **WHEN** 页面字段在两次轮询之间发生变化
- **THEN** 系统在下一次成功轮询完成后检测到变化，延迟约为轮询间隔加请求和解析时间
