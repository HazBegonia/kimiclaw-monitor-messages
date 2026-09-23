## Purpose

让上级只通过编辑 SKILL.md 的「采集需求」一节即可提出或变更监控需求；claw 理解需求并回显最终执行形态，经人在企业微信群内 @FF 确认后才激活落地，未确认的需求永远不影响采集脚本行为。

## ADDED Requirements

### Requirement: SKILL.md 采集需求段为唯一需求来源

系统 MUST 将 SKILL.md（intranet-message-triage）中的「采集需求」一节作为全部采集类需求（监控目标、关注版本清单等）的唯一来源；任何其他渠道（群聊、口头、手工改 config）MUST 不产生需求变更。

#### Scenario: 人修改需求段

- **WHEN** 人编辑 SKILL.md 的「采集需求」一节（新增、修改或删除需求）
- **THEN** 系统将其视为需求变更并进入理解-确认流程

#### Scenario: 手工编辑 config 不生效

- **WHEN** 人直接手工编辑 `config/intranet-versions.json` 或 `config/monitors.json` 而未改 SKILL.md
- **THEN** 系统在下一次同步时以已激活需求为准覆盖该文件，手工修改被丢弃

### Requirement: 需求变更检测

claw 的定时任务每轮 MUST 计算「采集需求」段的哈希（skillHash）并与需求台账比对；哈希一致时 MUST 不做任何需求同步动作（包括不重复发送确认消息）。

#### Scenario: 需求段未变化

- **WHEN** 本轮 skillHash 与台账中记录一致
- **THEN** claw 不生成新需求、不重发确认消息、不改写 config

#### Scenario: 需求段已变化

- **WHEN** 本轮 skillHash 与台账中记录不一致
- **THEN** claw 将台账中基于旧哈希的需求标记为「已被取代」，并基于新内容生成「待确认」需求

### Requirement: 理解回显与确认闸

claw 检测到需求变更后 MUST 将需求翻译为最终执行形态（将要写入台账与 config 的具体内容），并通过 FF 机器人发送群确认消息；该需求 MUST 保持「待确认」状态且不写入 config，直到人在群内 @FF 回复确认指令。

#### Scenario: 发送确认消息

- **WHEN** claw 生成新的「待确认」需求
- **THEN** FF 机器人向目标群发送包含最终执行形态的确认消息（监控目标、匹配文本、生效后的行为各是什么）

#### Scenario: 确认前不落地

- **WHEN** 需求处于「待确认」状态
- **THEN** `config/*.json` 不包含该需求对应的内容，采集脚本行为不变

#### Scenario: 确认后激活

- **WHEN** 人在群内 @FF 回复「开始」，且台账中存在「待确认」需求
- **THEN** 该需求状态变为「已激活」，claw 据此重新生成 config，并回执「已生效」及需求摘要

### Requirement: 需求台账

系统 MUST 在 `state/requirements.json` 维护需求台账；每条需求记录 MUST 包含：稳定 ID、最终执行形态、状态（待确认/已激活/已暂停/已被取代）、提出时间、最后状态变更时间、来源 skillHash。

#### Scenario: 状态可查

- **WHEN** 人在群内 @FF 发送「状态」
- **THEN** claw 回复台账中各需求的 ID、状态与摘要

#### Scenario: 暂停与恢复

- **WHEN** 人对已激活需求 @FF 发送「暂停」
- **THEN** 该需求变为「已暂停」并从 config 中移除对应内容，但台账保留记录；再次「开始」可恢复为「已激活」

### Requirement: 需求无过期

需求 MUST 不过期、不自动作废；其生命周期仅由 SKILL.md 变更与人的确认指令驱动。

#### Scenario: 长期未确认

- **WHEN** 需求处于「待确认」状态超过 24 小时且 SKILL.md 未再变化
- **THEN** 该需求保持「待确认」，config 不受影响，且不重复发送确认消息

### Requirement: config 生成幂等

claw 同步 config 时 MUST 仅在内容与已激活需求不一致时重写文件；一致时 MUST 不改动文件。

#### Scenario: 无漂移不重写

- **WHEN** config 内容与已激活需求推导结果完全一致
- **THEN** claw 不修改 config 文件，不产生任何留痕噪音
