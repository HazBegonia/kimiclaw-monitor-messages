## Purpose

为内网监控提供持久化、可检索且不泄露敏感信息的失败记录，使常驻进程和定时单次扫描都能被可靠诊断。

## ADDED Requirements

### Requirement: Record raw errors without business interpretation

系统 MUST 只记录可验证的技术错误事实，不在本能力内判断业务重要性、生成业务分析结论或发送通知。原始错误日志 MUST 保留稳定的事件标识，供后续 Claw skill 读取和处理。

#### Scenario: Raw error is recorded

- **WHEN** Python 监控流程发现可记录的技术错误
- **THEN** 系统写入原始错误记录，并只包含错误事实、阶段和运行上下文，不包含重要性等级或通知结论

#### Scenario: No notification in this capability

- **WHEN** 原始错误记录成功写入
- **THEN** 系统不发送企业微信、钉钉、邮箱或其他外部通知

### Requirement: Persist scan failures

系统 MUST 将每次扫描失败写入独立的错误日志，并至少记录检测时间、监控标识、失败阶段、异常类型、错误消息和相关状态处理结果。错误阶段 MUST 能区分配置读取、网页请求、页面校验、确认轮询、状态读取、正常日志写入和版本快照写入等操作。

#### Scenario: Network or page failure

- **WHEN** 内网请求超时、返回非成功 HTTP 状态、内容类型异常、页面签名校验失败或响应不完整
- **THEN** 系统写入一条对应阶段的错误记录，保留最近一次成功状态，不写入本轮正常变化日志或版本快照

#### Scenario: Invalid configuration or state

- **WHEN** 版本配置或状态文件不存在、无法读取、JSON 格式错误或内容不符合要求
- **THEN** 系统写入包含文件路径和错误阶段的错误记录，并通过现有失败返回行为报告本轮扫描失败

#### Scenario: Persistence failure

- **WHEN** 正常日志、版本快照或状态文件无法写入
- **THEN** 系统写入持久化失败记录（若错误日志目录仍可写），不得把该轮标记为成功

### Requirement: Support execution modes and fallback

系统 MUST 在常驻模式记录错误后继续下一轮扫描；在 `--once` 模式发生错误时 MUST 返回非零退出码。错误日志自身无法写入时，系统 MUST 将精简错误信息回退到 stderr，且不得因记录错误再次覆盖或破坏最近一次成功状态。

#### Scenario: Resident monitor continues

- **WHEN** 常驻模式的一轮扫描失败
- **THEN** 系统记录错误并继续按配置间隔执行后续扫描

#### Scenario: Single scan reports failure

- **WHEN** `--once` 模式的一轮扫描失败
- **THEN** 系统记录错误并返回非零退出码供 OpenClaw cron 判断

#### Scenario: Error log fallback

- **WHEN** 错误日志目录不可写
- **THEN** 系统将不含敏感凭据的错误摘要输出到 stderr，并保留原始异常返回语义

### Requirement: Protect sensitive data and manage growth

错误日志 MUST 不包含认证 Token、完整网页响应、CSV 正文或其他认证凭据。错误日志格式 MUST 支持按时间检索，并提供可配置或文档化的保留/清理策略以限制长期磁盘增长。

#### Scenario: Sensitive data is omitted

- **WHEN** 错误上下文包含认证信息或网页响应
- **THEN** 错误记录只保留脱敏后的 URL、状态码、异常类型和摘要，不写入 Token、响应正文或 CSV 内容

#### Scenario: Retention is applied

- **WHEN** 错误日志超过配置或文档规定的保留期限或大小上限
- **THEN** 系统按既定策略清理旧错误日志，并保留新近错误记录可供排查
