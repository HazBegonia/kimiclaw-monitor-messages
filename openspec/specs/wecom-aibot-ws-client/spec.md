# wecom-aibot-ws-client Specification

## Purpose

以 py 原生实现企业微信智能机器人长连接协议的发送能力，使监控推送不再依赖 OpenClaw 运行时；同时约束认证、回执与连接独占，保证通道行为可预期、凭证不泄密。

## Requirements

### Requirement: 长连接认证

客户端 MUST 按官方长连接协议连接服务端并发送认证帧（botId 与 secret）；服务端回执 errcode 为 0 视为认证成功，非 0 视为认证失败并向调用方返回明确错误。凭证错误 MUST NOT 被静默吞掉或无限重试。

#### Scenario: 认证成功

- **WHEN** 以正确 botId 与 secret 发起连接
- **THEN** 认证回执 errcode 为 0，客户端进入可用状态

#### Scenario: 凭证错误可见

- **WHEN** secret 错误导致认证回执非 0
- **THEN** 调用方收到认证失败错误，本次推送记为失败

### Requirement: 按需连接发送

本阶段客户端 MUST 按需使用连接：仅当存在待发送消息时建立连接，完成认证、发送并取得回执后即断开；无消息时 MUST NOT 维持长连接或心跳。连接、认证、发送任一步失败或超时，MUST 整体记为本次发送失败。

#### Scenario: 有消息才连接

- **WHEN** 一轮产生重要消息需要推送
- **THEN** 客户端建立连接、认证、发送、等待回执后关闭连接

#### Scenario: 步骤超时判失败

- **WHEN** 发送回执在超时时间内未到达
- **THEN** 本次发送记为失败，不产生半成功状态

### Requirement: 主动推送回执

主动推送 MUST 使用协议的主动发送通道，消息体携带目标 chatid 与 markdown 内容；发送结果以请求标识对应的回执为准，回执 errcode 为 0 记成功，非 0 记失败并保留错误码与摘要供留痕。

#### Scenario: 推送成功

- **WHEN** 向有效 chatid 发送 markdown 且回执 errcode 为 0
- **THEN** 本次推送记为成功

#### Scenario: 目标失效报错

- **WHEN** chatid 因机器人被移出群而失效
- **THEN** 回执非 0，失败被留痕，下轮重试持续可见

### Requirement: 连接独占约束

同一 botId 的服务端连接具有独占性：新连接会使旧连接被服务端断开。系统 MUST 保证同一凭证同一时刻只由一个客户端使用；通知器切换到生产机器人凭证前，MUST 先停止既有的 OpenClaw gateway 通道，避免互踢抖动。

#### Scenario: 切换顺序

- **WHEN** 通知器准备以生产机器人凭证运行
- **THEN** OpenClaw gateway 已先行停止，通知器是唯一持连接者

#### Scenario: 被顶连接可感知

- **WHEN** 服务端因新连接而断开当前连接
- **THEN** 客户端将受影响的发送记为失败或感知断开并留痕，不误报成功

### Requirement: 凭证不入仓库

机器人 Bot ID 与 Secret MUST 仅存于 gitignore 覆盖的本地目录（`state/secrets/`）；仓库（含 git 历史）MUST NOT 出现明文 Secret，配置文件仅引用 secrets 文件路径。chatid 不属于密钥，允许出现在配置中。

#### Scenario: 密钥不入库

- **WHEN** 检查项目仓库与 git 历史
- **THEN** 不存在机器人 Secret 明文，配置仅保存 secrets 文件路径引用
