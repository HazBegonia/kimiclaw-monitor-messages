# wecom-aibot-notify Specification (delta)

## MODIFIED Requirements

### Requirement: 企业微信智能机器人渠道建立

系统 SHALL 通过 py 原生实现的智能机器人长连接客户端（见 wecom-aibot-ws-client 能力域）建立到企业微信的出站连接，并支持向会话主动推送消息；MUST NOT 依赖 OpenClaw gateway 或任何 LLM 会话在线。机器人凭证（Bot ID、Secret）MUST 仅存于 gitignore 覆盖的本地 secrets 文件；项目仓库内 MUST NOT 出现明文 Secret。

#### Scenario: 渠道上线

- **WHEN** 通知器以正确凭证向长连接端点发起连接并完成认证
- **THEN** 主动推送通道可用，全程不依赖 OpenClaw gateway 或任何 LLM 会话

#### Scenario: 密钥不入库

- **WHEN** 检查项目仓库（含 git 历史）
- **THEN** 不存在机器人 Secret 的明文记录，项目内仅保存 secrets 文件路径引用

### Requirement: 目标会话激活与标识持久化

系统 SHALL 以配置文件中的 chatid 作为主动推送目标；chatid 的取值前提保持不变——目标群内须有人 @机器人 发送过消息完成会话激活。机器人被移出群再加回导致推送失效时，人 MUST 在群内重新 @机器人 一次并人工核对更新配置中的 chatid。chatid 不属于密钥，允许入库。

#### Scenario: 激活并记录 chatid

- **WHEN** 群成员在目标群 @机器人 发送消息完成会话激活，且配置中的 chatid 与该群当前会话一致
- **THEN** 后续主动推送以该 chatid 为目标送达

#### Scenario: 失效后人工恢复

- **WHEN** 机器人被移出群再加回导致推送回执失败
- **THEN** 人在群内重新 @机器人 并核对配置 chatid 后，推送恢复
