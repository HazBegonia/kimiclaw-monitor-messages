# wecom-aibot-notify Specification

## Purpose

将内网监控中经重要性判定后的关键消息（文件变更、监控错误），通过企业微信智能机器人长连接渠道实时推送到指定企业微信会话（群聊或私聊），使责任人无需查看本地日志即可及时获知。

## Requirements

### Requirement: 企业微信智能机器人渠道建立

系统 SHALL 通过 py 原生实现的智能机器人长连接客户端（见 wecom-aibot-ws-client 能力域）建立到企业微信的出站连接，并支持向会话主动推送消息；MUST NOT 依赖 OpenClaw gateway 或任何 LLM 会话在线。机器人凭证（Bot ID、Secret）MUST 仅存于 gitignore 覆盖的本地 secrets 文件；项目仓库内 MUST NOT 出现明文 Secret。

#### Scenario: 渠道上线

- **WHEN** 通知器以正确凭证向长连接端点发起连接并完成认证
- **THEN** 主动推送通道可用，全程不依赖 OpenClaw gateway 或任何 LLM 会话

#### Scenario: 密钥不入库

- **WHEN** 检查项目仓库（含 git 历史）
- **THEN** 不存在机器人 Secret 的明文记录，项目内仅保存 secrets 文件路径引用

### Requirement: 目标会话激活与标识持久化

系统 SHALL 以配置文件中的 chatid 与 chatType 作为主动推送目标。chatType=1 时 chatid 为用户 userid，目标为私聊；chatType=2 时 chatid 为群 chatid，目标为群聊；缺少 chatType 时按群聊兼容。目标会话必须先完成交互：群聊中须有人 @机器人 发过消息，私聊中须由目标用户给机器人发过消息。chatid 与 chatType 不属于密钥，允许入库。

#### Scenario: 激活并记录群聊目标

- **WHEN** 群成员在目标群 @机器人 发送消息完成会话激活，且配置中的 chatid 与该群当前会话一致、chatType=2
- **THEN** 后续主动推送到该群

#### Scenario: 激活并记录私聊目标

- **WHEN** 用户在机器人私聊中发送过消息，且配置中的 chatid 为该用户 userid、chatType=1
- **THEN** 后续主动推送到该用户与机器人的私聊

#### Scenario: 群聊失效后人工恢复

- **WHEN** 机器人被移出群再加回导致推送回执失败
- **THEN** 人在群内重新 @机器人 并核对配置 chatid 后，推送恢复

### Requirement: 重要监控消息推送

系统 SHALL 对监控产物做重要性判定；判定为重要的新增/删除文件变更（flow1）与监控错误（flow2）MUST 通过机器人主动推送到目标会话。同一轮扫描产生的多条重要消息 SHOULD 聚合为一条推送。不重要或无变化的产物 MUST NOT 触发推送。

#### Scenario: 重要变更推送

- **WHEN** 一轮监控扫描产生新增文件且被判定为重要
- **THEN** 目标会话在当轮处理完成后收到一条包含文件名与时间的推送消息

#### Scenario: 无重要变化不打扰

- **WHEN** 一轮监控扫描无变化或仅有被判定为不重要的产物
- **THEN** 目标会话不收到任何推送

#### Scenario: 重要错误推送

- **WHEN** 监控错误日志中出现被判定为重要的错误记录
- **THEN** 目标会话收到一条包含错误阶段与脱敏摘要的推送消息

### Requirement: 推送频控约束

系统 MUST 遵守企业微信推送频率限制（每会话 30 条/分钟、1000 条/小时）；当一轮重要消息超过限额时，系统 MUST 聚合或延迟发送而不是超限推送。

#### Scenario: 大量变更聚合

- **WHEN** 一轮扫描产生大量重要变更（如超过 20 个新文件）
- **THEN** 仅发送聚合后的少量消息，且不触发企微频控错误

### Requirement: 推送失败可观测

推送失败（网络异常、凭证失效、频控错误等）MUST 被记录到本地日志，包含失败原因与失败的消息内容，且不中断既有监控扫描流程。

#### Scenario: 推送失败留痕

- **WHEN** 向目标会话推送消息失败
- **THEN** 本地日志出现一条包含错误码/异常信息与消息摘要的记录，监控扫描继续正常运行
