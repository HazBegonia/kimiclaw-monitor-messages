# skill-driven-requirement-lifecycle Specification (delta)

## MODIFIED Requirements

### Requirement: SKILL.md 采集需求段为唯一需求来源

系统 MUST 将 SKILL.md（intranet-message-triage）中的「采集需求」一节作为全部采集类需求（监控目标、关注版本清单、扫描频率等）的唯一来源；任何其他渠道（群聊、口头、手工改 config、手工改计划任务）MUST 不产生需求变更。

#### Scenario: 人修改需求段

- **WHEN** 人编辑 SKILL.md 的「采集需求」一节（新增、修改或删除需求）
- **THEN** 系统将其视为需求变更并进入理解-确认流程

#### Scenario: 手工编辑 config 不生效

- **WHEN** 人直接手工编辑 `config/intranet-versions.json` 或 `config/monitors.json` 而未改 SKILL.md
- **THEN** 系统在下一次同步时以已激活需求为准覆盖该文件，手工修改被丢弃

#### Scenario: 手工改计划任务不生效

- **WHEN** 人直接手工修改 Windows 计划任务（频率、命令行等）而未改 SKILL.md
- **THEN** 系统在下一次需求同步时以已激活需求为准重建计划任务，手工修改被丢弃

### Requirement: 理解回显与确认闸

claw 检测到需求变更后 MUST 将需求翻译为最终执行形态（将要写入台账与 config 的具体内容），并通过 FF 机器人发送群确认消息；该需求 MUST 保持「待确认」状态且不写入 config、不更新计划任务，直到人在群内 @FF 回复确认指令。

#### Scenario: 发送确认消息

- **WHEN** claw 生成新的「待确认」需求
- **THEN** FF 机器人向目标群发送包含最终执行形态的确认消息（监控目标、匹配文本、扫描频率、生效后的行为各是什么）

#### Scenario: 确认前不落地

- **WHEN** 需求处于「待确认」状态
- **THEN** `config/*.json` 不包含该需求对应的内容，Windows 计划任务不更新，采集脚本行为不变

#### Scenario: 确认后激活

- **WHEN** 人在群内 @FF 回复「开始」，且台账中存在「待确认」需求
- **THEN** 该需求状态变为「已激活」，claw 据此重新生成 config 并注册/更新 Windows 计划任务，并回执「已生效」及需求摘要

## ADDED Requirements

### Requirement: 扫描频率纳入需求管理

「采集需求」机器可读块 MUST 支持 `scanIntervalMinutes` 字段（缺省视为 1 分钟）；需求激活后，Windows 计划任务的扫描间隔 MUST 与已激活需求的该字段一致。

#### Scenario: 缺省频率

- **WHEN** 「采集需求」块未声明 `scanIntervalMinutes`
- **THEN** 计划任务按 1 分钟间隔注册

#### Scenario: 修改频率经确认生效

- **WHEN** 人将 `scanIntervalMinutes` 改为 5 并经 @FF 确认激活
- **THEN** 计划任务扫描间隔更新为 5 分钟
