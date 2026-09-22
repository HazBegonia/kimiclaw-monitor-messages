# skill-driven-requirement-lifecycle Delta Spec

## MODIFIED Requirements

### Requirement: SKILL.md 采集需求段为唯一需求来源

系统 MUST 将 SKILL.md（intranet-message-triage）中的「采集需求」一节作为全部采集类需求（监控目标、关注版本清单、扫描频率等）的唯一来源。变更只能经两种途径进入该节：人直接编辑文件；或人在群内 @FF 提出变更、经草案「写入」确认后由 claw 代笔写入该节。两种途径 MUST 汇流到同一套需求同步与确认闸流程，等价对待。除此之外的任何渠道（口头、手工改 config、手工改计划任务、未经「写入」确认的群聊消息）MUST 不产生需求变更。

#### Scenario: 人修改需求段

- **WHEN** 人编辑 SKILL.md 的「采集需求」一节（新增、修改或删除需求）
- **THEN** 系统将其视为需求变更并进入理解-确认流程

#### Scenario: claw 代笔写入需求段

- **WHEN** 群内变更草案经人 @FF 回复「写入」确认
- **THEN** claw 将草案内容写入「采集需求」节，触发与人工编辑等价的需求同步与确认流程，激活仍需人回复「开始」

#### Scenario: 未经写入的群聊请求不生效

- **WHEN** 人在群内 @FF 提出变更但未回复「写入」（草案处于待写入/已放弃/已被取代）
- **THEN** 「采集需求」节内容不变，不产生任何需求变更

#### Scenario: 手工编辑 config 不生效

- **WHEN** 人直接手工编辑 `config/intranet-versions.json` 或 `config/monitors.json` 而未改 SKILL.md
- **THEN** 系统在下一次同步时以已激活需求为准覆盖该文件，手工修改被丢弃

#### Scenario: 手工改计划任务不生效

- **WHEN** 人直接手工修改 Windows 计划任务（频率、命令行等）而未改 SKILL.md
- **THEN** 系统在下一次需求同步时以已激活需求为准重建计划任务，手工修改被丢弃
