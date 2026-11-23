# ff-config-assistant Specification

## Purpose

上级在企微群 @FF 用自然语言提出监控需求变更，Claw 作为配置助手理解需求、起草变更、经群内确认后修改白名单内的 config 文件，并在写后校验失败时自动回滚——让「对话即需求入口」在边界受控、全程留痕的前提下成立。

## Requirements

### Requirement: 需求理解与草案起草

@FF 会话收到变更类请求时，Claw MUST 先把理解落成草案：生成草案记录（含原始请求、理解、目标文件、改前内容、改后内容、校验命令、时间戳、状态）存入 `state/chat-drafts.json`，并在群内回显改前/改后对照供人核对。草案未确认前 MUST NOT 修改目标 config 文件或业务系统状态；只允许写入草案台账和操作留痕。同一时刻 MUST 至多一个待写入草案，新草案顶掉旧草案（旧草案标记被取代）。

歧义请求 MUST 只追问不动笔；无法解析的请求 MUST 回固定帮助（能改什么、怎么确认）。

#### Scenario: 增加关注字段

- **WHEN** 群内收到「@FF 增加字段 103300110003 的监控」
- **THEN** Claw 起草一条目标为 `config/intranet-versions.json` 的草案，群内回显改前（仅 103300110002）与改后（两条）对照，且此时目标 config 未被修改，草案台账已保存记录

#### Scenario: 新草案顶掉旧草案

- **WHEN** 已存在一个待写入草案时又收到新的变更请求
- **THEN** 旧草案状态置为被取代，新草案成为唯一待写入草案，群内提示顶掉关系

#### Scenario: 歧义请求只追问

- **WHEN** 收到「@FF 把监控调一下」这类无法落到具体键值的请求
- **THEN** Claw 回追问问题，不产生草案、不改文件

### Requirement: 确认闸

仅逐字指令「写入」「放弃」作用于待写入草案：「写入」触发落盘流程；「放弃」将草案置为已放弃。其他消息 MUST NOT 改变目标 config 或业务系统状态；新的明确变更请求仍可按起草流程更新草案台账并顶掉旧草案。Claw 每次收到群消息时若存在待写入草案，MUST 提示有草案待确认（抵御推送窗口丢消息导致的确认丢失）。对已完成（已写入/已放弃/被取代）草案重复发送「写入」MUST 幂等回复当前状态，不重复落盘。

#### Scenario: 写入确认

- **WHEN** 草案待写入时群内收到逐字「写入」
- **THEN** 执行落盘与写后校验，群内报告结果

#### Scenario: 自然语言不触发修改

- **WHEN** 草案待写入时收到「嗯」「好的」「可以」之类的非逐字回复
- **THEN** 不修改任何文件，提示须回「写入」或「放弃」

#### Scenario: 确认消息被推送窗口吞掉

- **WHEN** 上级回过「写入」但该消息在推送窗口内被服务器丢弃，随后上级发来任意新消息
- **THEN** Claw 提示仍有草案待写入，上级重发「写入」即可继续

### Requirement: 白名单边界

对话修改 MUST 仅限白名单内目标：`config/intranet-versions.json`（关注版本 CRUD，含每选择项的 `id`、`match` 与可选 `mode`）、`config/monitors.json`（监控目标 CRUD）、`config/triage-rules.json`（推送规则条目级，含 `push.diff.filenameIncludePatterns` 关注模式）、`config/notifier.json`（chatid）、`config/notify-template.json`（通知文案、区块及顺序）。白名单外的一切目标（源代码、`.env`、密钥、systemd unit、轮询间隔、skill 文件自身）MUST 拒绝并说明原因与人工处理路径。白名单本身只能由人直接编辑 skill 文件修改，MUST NOT 走对话。

#### Scenario: 白名单内修改被受理

- **WHEN** 收到「@FF 删除字段 103300110002」
- **THEN** 正常起草 `config/intranet-versions.json` 草案

#### Scenario: 关注模式修改被受理

- **WHEN** 收到「@FF 以后新增文件只推文件名带 103300110002 的」
- **THEN** 正常起草 `config/triage-rules.json` 草案，条目级修改 `push.diff.filenameIncludePatterns`

#### Scenario: 匹配模式修改被受理

- **WHEN** 收到「@FF 把字段 103300110002 的匹配改成通配符 report-*-103300110002.csv」
- **THEN** 正常起草 `config/intranet-versions.json` 草案，将该选择项的 `mode` 置为 `fnmatch`

#### Scenario: 白名单外修改被拒绝

- **WHEN** 收到「@FF 把轮询间隔改成 2 秒」
- **THEN** 回复拒绝，说明需人工修改采集器 `.env` 或通知器 JSON 中的间隔并重启对应服务，不产生草案

### Requirement: 写后校验与自动回滚

「写入」落盘后 MUST 立即执行该校验目标绑定的校验（至少：JSON 可解析 + 对应 py 加载器/校验器通过），并回读文件确认内容与草案改后一致。任一校验失败 MUST 用草案中的改前内容自动回滚，群内报告「写入失败已回滚，配置未变」。全部通过 MUST 群内报告实际生效范围与生效时机：监控目标、关注字段和推送规则在下一轮采集或判定时生效，通知模板在下一次通知时生效，`config/notifier.json` 需人工重启通知器后生效。

#### Scenario: 校验通过生效

- **WHEN** 「写入」后 JSON 解析与 py 校验器均通过
- **THEN** 草案置为已写入，群内报告生效范围

#### Scenario: 校验失败自动回滚

- **WHEN** 「写入」后校验器拒绝新内容
- **THEN** 文件还原为草案改前内容，草案置为已回滚，群内报告失败原因，系统状态与写入前一致

### Requirement: 全程留痕

草案的每次状态变化（起草、顶掉、写入、放弃、回滚）MUST 追加一行 JSONL 到 `logs/intranet-notify/` 当日文件（stage: config-change），含草案 id、原始请求、目标文件与结果。留痕失败 MUST NOT 阻断主流程，但须在群内报告中注明留痕失败。

#### Scenario: 写入留痕

- **WHEN** 一条草案完成「写入」
- **THEN** 当日 `logs/intranet-notify/` 文件中存在该草案 stage=config-change 的成功留痕行

### Requirement: 只读查询

状态类问题（当前监控哪些字段、推送规则是什么、草案状态等）MUST 通过读取 config 与 state 文件直接回答，MUST NOT 产生草案或修改文件。

#### Scenario: 查询当前关注版本

- **WHEN** 收到「@FF 现在监控哪些字段？」
- **THEN** Claw 读取 `config/intranet-versions.json` 并回答，不产生草案
