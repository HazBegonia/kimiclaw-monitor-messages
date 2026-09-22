# chat-driven-skill-config-editing Delta Spec

## Purpose

让上级在企业微信群内用自然语言向 FF 提出对 skill（采集需求块、重要性判定规则）与白名单运维 config 的变更：claw 把模糊人话翻译为精确改动并回显改前/改后对照，经人回复「写入」确认后才落盘，落盘后校验、失败自动回滚，全程留痕可审计。

## ADDED Requirements

### Requirement: 意图分类与只读查询

@FF 会话收到非控制指令的消息后，MUST 先做意图分类：需求块修改 / 重要性规则修改 / 运维 config 修改 / 只读查询 / 无法解析。只读查询 MUST 直接回答且不改变任何状态；无法解析的消息 MUST 不改变任何状态并回复固定帮助文案。

#### Scenario: 只读查询直接回答

- **WHEN** 人在群内 @FF 发送「现在监控哪些版本？」
- **THEN** claw 依据当前已激活需求回答，不生成草案、不改变任何状态

#### Scenario: 无法解析回帮助

- **WHEN** 人在群内 @FF 发送与监控变更无关或无法理解的消息
- **THEN** claw 不改变任何状态，回复固定帮助文案（可用指令与可变更对象说明）

### Requirement: 草案生成与对照回显

变更类意图 MUST 先生成草案并写入 `state/chat-drafts.json`，群内回复 MUST 包含：对请求的理解、改前→改后对照、最终执行形态、操作指引（「确认请回复：写入 / 放弃」）。草案记录 MUST 包含：人发送的原话、解析结果、目标对象类型（需求块/规则/config）、改前与改后内容、提出时间、状态（待写入/已写入/已放弃/已被取代）。生成草案 MUST NOT 改动任何 skill 或 config 文件。

#### Scenario: 生成草案不动文件

- **WHEN** 人 @FF 发送「关注版本加一个 103300110004」
- **THEN** 草案落 `state/chat-drafts.json`，群内收到改前→改后对照，SKILL.md 与 config 内容不变

### Requirement: 单待写入草案

同一时刻 MUST 最多存在一个「待写入」草案；生成新草案时，既有「待写入」草案 MUST 标记为「已被取代」。

#### Scenario: 新草案取代旧草案

- **WHEN** 存在「待写入」草案且人又提出新变更请求
- **THEN** 旧草案标记「已被取代」，新草案成为唯一「待写入」草案，群内回复中提示旧草案已作废

### Requirement: 写入与放弃指令

「写入」指令 MUST 仅当存在「待写入」草案时生效：将草案内容落盘到目标文件，并把草案标记为「已写入」；无待写入草案时回复当前状态提示。「放弃」指令 MUST 将「待写入」草案标记为「已放弃」，不改动任何文件；无待写入草案时不改变任何状态。

#### Scenario: 写入落盘

- **WHEN** 存在「待写入」草案且人 @FF 回复「写入」
- **THEN** 草案内容落盘到目标文件，草案标记「已写入」，进入对应生效路径（见「分类生效路径」）

#### Scenario: 放弃作废

- **WHEN** 存在「待写入」草案且人 @FF 回复「放弃」
- **THEN** 草案标记「已放弃」，所有文件与系统状态不变

### Requirement: 歧义只追问不动笔

解析结果存在歧义（如指代不明、多候选对象、缺关键参数）时，claw MUST 回复澄清问题，MUST NOT 生成草案，MUST NOT 改动任何文件。

#### Scenario: 指代不明时追问

- **WHEN** 已激活版本有多个，人 @FF 发送「把那个旧版本删了」
- **THEN** claw 回复追问（列出候选版本请其指明），不生成草案、不改变任何状态

### Requirement: 写后校验与自动回滚

草案落盘后 MUST 立刻校验目标文件：SKILL.md 的 ```json monitor-requirements 块可提取且 JSON 可解析、块外结构与既有章节完好；config 文件 JSON 可加载；wecom 群名类变更 MUST 额外验证目标群可解析（如 sessions list 能匹配到新群名）。校验失败 MUST 将目标文件回滚到落盘前内容，群内报告失败原因，且不改变台账、游标等任何系统状态。

#### Scenario: SKILL.md 校验失败回滚

- **WHEN** 草案写入 SKILL.md 后需求块无法解析
- **THEN** SKILL.md 回滚到写入前内容，群内收到失败报告，需求同步流程不被触发

#### Scenario: 群名变更验证失败回滚

- **WHEN** 草案修改 wecom 群名后，sessions list 中找不到新群
- **THEN** config 回滚到修改前内容，群内收到失败报告（推送通道保持原样可用）

### Requirement: 分类生效路径

草案落盘后的生效路径 MUST 按目标对象类型区分：需求块草案写入 SKILL.md 后 MUST 走既有需求同步流程（hash 检测 → 群确认 →「开始」激活后才派生 config 与计划任务），MUST NOT 直接改写 config；重要性规则草案写入即生效（triage 每轮重读规则）；运维 config 草案写入即生效并完成写后验证。

#### Scenario: 需求块草案仍需开始激活

- **WHEN** 需求块草案已「写入」SKILL.md
- **THEN** 系统发送需求确认消息，config 与计划任务保持原样，直到人 @FF 回复「开始」

#### Scenario: 规则草案写入即生效

- **WHEN** 重要性规则草案已「写入」SKILL.md 且校验通过
- **THEN** 下一轮 triage 起按新规则判定，无需再确认

### Requirement: 运维 config 白名单

可经对话修改的 config 文件及字段 MUST 以白名单形式明确列于 SKILL.md；白名单之外的文件或字段，claw MUST 拒绝并提示手工修改。

#### Scenario: 白名单外拒绝

- **WHEN** 人 @FF 请求修改白名单之外的 config 内容（如 openclaw 全局配置）
- **THEN** claw 拒绝并回复该配置须手工修改，不生成草案

### Requirement: 草案留痕

草案生命周期的每个事件（生成、取代、写入、放弃、校验失败回滚）MUST 往 `logs/intranet-notify/` 当日文件追加一行 JSONL 留痕：`{"detectedAt", "stage": "chat-draft", "action": "<事件>", "draftId", "requestDigest": "<原话前 80 字符>"}`。

#### Scenario: 写入留痕

- **WHEN** 任一草案事件被处理
- **THEN** `logs/intranet-notify/` 当日文件新增对应 JSONL 行，可据此审计谁在何时改了什么
