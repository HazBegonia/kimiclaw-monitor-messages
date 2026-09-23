---
name: intranet-message-triage
description: 内网监控消息的重要性判定与企业微信推送，兼管采集需求闭环与对话草案。由事件唤醒（py 检测到新 diff/错误日志后 spawn 本会话）或兜底轮询（OpenClaw cron 每 10 分钟）触发：读取 logs/intranet-diff/ 与 logs/intranet-error/ 的新增产物，判定重要性，将重要消息聚合成一条 markdown 通过企微 FF 机器人（wecom 渠道）推送到全员群，并推进 state/notify-state.json 游标；同时负责把「采集需求」节的需求经群内确认后同步为 config 与 Windows 常驻守护任务，并在 @FF 交互会话中响应 开始/暂停/状态/写入/放弃 控制指令、把群内自然语言变更请求起草为草案（经「写入」确认后落盘 SKILL.md 采集需求节/重要性规则节或白名单 config，写后校验失败自动回滚）及回答只读查询。
user-invocable: true
---

# 内网监控消息重要性判定与推送（flow1 / flow2 末端）

> **⚠️ 已退役（2026-09-18，change: retire-openclaw-py-notifier）**：OpenClaw 已整体停用，本 skill 不再被任何运行中链路读取。重要性判定已机器化为 `config/triage-rules.json`（通知器每轮热读，语义与本文件「重要性判定规则」节逐条对齐：新增/删除默认推；PageValidationError 与 read_config/write_state/write_snapshot_log/read_rules 阶段推；孤立可重试抖动抑制 + 同 monitorId/phase 30 分钟窗口 ≥3 次升级）。推送由 `src/intranet_notifier` 经企微智能机器人长连接直接完成，全链路 0 token。本文件保留作需求记录与审计；「采集需求」节是将来用 py 重建需求闭环的入口。

触发方式有两种，triage 流程本身不变：

1. **事件唤醒（主）**：py 扫描脚本检测到新 diff 或新错误日志后，spawn 一次性 agent 会话执行本流程。无新产物时不会有任何会话被唤起。
2. **兜底轮询（辅）**：OpenClaw cron 每 10 分钟唤起一次兜底轮，职责限于「需求同步」、事件链故障检查（见「事件链故障告警」）、游标落后补扫；全无动作时直接结束，不发任何消息。

三条铁律：

1. **不重要的不发，无变化的不发** —— 群里只出现值得李非凡看的消息。
2. **一轮最多一条推送** —— 本轮所有重要内容聚合为一条 markdown（企微频控 30 条/分钟、1000 条/小时/会话，聚合后远低于限额）。
3. **发送成功才推进游标** —— 失败留痕、下轮重试，不允许静默丢消息。

## 职责边界

- 「监控什么」（目标页面、关注版本）的唯一来源是本文件的「采集需求」节，变更必须过确认闸（见「需求同步」），未确认前不影响脚本。
- 「采集需求」节只能经两种途径变化：人直接编辑文件；或群内 @FF 提出变更、经草案「写入」确认后由 claw 代笔写入（见「对话草案」）。两种途径等价，都走「需求同步」确认闸；除此之外的任何渠道（口头、手工改 config、未经「写入」的群聊消息）一律不生效。
- 「重要性判定规则」一节只影响 claw 的推送判断，不影响脚本行为；人直接编辑立即生效，对话草案按条目级变更经「写入」后生效。
- 群聊可发起变更草案与只读查询，但草案未「写入」前不改变任何文件与系统状态；白名单外的 config 一律拒绝对话修改（见「对话草案 · 运维 config 白名单」）。

## triage 互斥锁（state/triage.lock）

事件唤醒会话、兜底轮补扫、@FF 会话里的 triage 都可能并发，执行 triage 前 MUST 先取得互斥锁：

1. 原子创建 `state/triage.lock`（已存在则创建失败），内容一行 JSON：`{"acquiredAt": "<ISO8601>"}`。
2. 锁已存在：读 `acquiredAt`，距今 ≤15 分钟 → 另有 triage 正在执行，本轮直接结束（不读取也不推进游标）；>15 分钟 → 视为异常退出的遗留锁，删除后重试一次。
3. triage 结束（无论成功、失败还是无事可做）MUST 删除锁文件。
4. @FF 控制指令（开始/暂停/状态）不涉及游标，不取锁；台账仍按「原子写 + 写前重读」约定。

## 输入

| 来源 | 位置 | 格式 |
|---|---|---|
| flow1 变更日志 | `logs/intranet-diff/*.log` | 类 YAML：`detectedAt`、`changedFields: - root_files: {"added": [...], "removed": [...]}` |
| flow1 版本快照 | `logs/intranet-focus/<版本ID>/*.log` | 类 YAML：`versionId`、`match`、`count`、`files` 全量清单。原始材料，可用于在架清单核对；是否参与判定由「重要性判定规则」决定 |
| flow2 错误日志 | `logs/intranet-error/YYYY-MM-DD.log` | JSONL，每行字段：`eventId` `detectedAt` `phase` `errorType` `message` `statePreserved` `retryable` |
| 推送游标 | `state/notify-state.json` | `{"diffCursor": "<已处理到的 diff 文件名>", "errorCursor": {"date": "<日期>", "offset": <已处理行数>}}` |
| 需求台账 | `state/requirements.json` | 见「需求台账」节 |
| 互斥锁 | `state/triage.lock` | 单行 JSON：`{"acquiredAt": "<ISO8601>"}`，见「triage 互斥锁」节 |
| 事件队列 | `state/openclaw-pending/*.json` | py 唤醒失败时积压的唤醒事件：`eventId`、`monitor_id`、`log_path`、`detected_at`；见「事件链故障告警」节 |
| 草案文件 | `state/chat-drafts.json` | 对话草案台账，见「对话草案」节 |

只处理**游标之后**的新产物：diff 按文件名（时间戳）排序取 `diffCursor` 之后的 `.log`；error 取当日文件 `offset` 行之后的新行（跨天则从 `errorCursor.date` 之后的日期文件第 0 行开始）。

## 采集需求（需求变更的唯一来源）

上级要调整"监控什么"，改本节——人直接编辑，或群内 @FF 提出后经草案「写入」由 claw 代笔写入（见「对话草案」），然后等 FF 在群里发确认消息，确认后才生效。脚本不读本文件；本节由 claw 按「需求同步」流程落到 config。

- `targets`：监控目标列表，每项含 `id`（稳定标识，同时用作 monitorId 与 state 文件名）、`url`、`profile`（字段提取规格）。
- `versions`：关注版本列表，每项含 `id` 与 `match`（文件名匹配文本）。脚本按此为每个版本留全量快照到 `logs/intranet-focus/`，快照用途由「重要性判定规则」决定，脚本不做重要性判断。
- `scanIntervalSeconds`：Windows 常驻守护任务的轮询间隔（秒），缺省视为 5；取值范围 2–3600。激活后由 claw 重建守护任务并重启常驻扫描，脚本本身不读该字段。

机器可读块是本节的准绳：人话与块冲突时以块为准，并在确认消息中提醒人修正人话。

```json monitor-requirements
{
  "scanIntervalSeconds": 5,
  "targets": [
    {
      "id": "intranet-root",
      "url": "http://172.16.30.20:8011/",
      "profile": {"root_files": {"type": "link_set", "extension": ".csv"}}
    }
  ],
  "versions": [
    {"id": "103300110002", "match": "103300110002"},
    {"id": "103300110009", "match": "103300110009"}
  ]
}
```

## 需求同步（兜底轮每轮最先执行）

1. 提取本文件「采集需求」节的 ```json monitor-requirements 块，对块内文本（去除首尾空白）算 sha256，得 `skillHash`。
2. 读 `state/requirements.json`（不存在视为空台账）。
3. `skillHash` 与台账顶层 `skillHash` 一致 → 跳到第 5 步；不一致 → 继续第 4 步。
4. 需求变更处理（确定性提取 json 内容，不做自由发挥）：
   a. 台账中所有非终态需求标记为「已被取代」。
   b. 生成新需求：`targets` 整体一条（id `req-targets`），`versions` 整体一条（id `req-versions`），`scanIntervalSeconds` 整体一条（id `req-scan-interval`，缺省按 5 生成），状态「待确认」，`content` 为最终执行形态；旧字段 `scanIntervalMinutes` 忽略。
   c. 通过 wecom-cli 向「未命名企业」群发一条确认消息（发送方式同「发送方式」节），内容：人话摘要 + 最终执行形态（json 原文）+ 操作指引「确认请 @FF 回复：开始」。多条需求合并为一条消息，一轮最多一条。
   d. 更新台账顶层 `skillHash`。
5. 生成 config 与同步常驻守护任务（幂等，内容一致不重写文件）：
   - 「已激活」的 `req-targets` → `config/monitors.json` 的 `targets` 数组原样照抄。
   - 「已激活」的 `req-versions` → `config/intranet-versions.json` 的 `selectedVersions` 数组原样照抄。
   - 「已激活」的 `req-scan-interval` → 先调用 `scripts/register-windows-scheduler.ps1 -Action Stop`，再调用 `scripts/register-windows-scheduler.ps1 -IntervalSeconds <值>` 重建 Windows 常驻守护任务并用 `-Action Run` 重启扫描进程（值与当前一致时跳过）。调用方式：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File <项目根绝对路径>\scripts\register-windows-scheduler.ps1 <参数>`。
   - 铁律：config 与常驻守护任务是台账的确定性派生产物，禁止添加、推测、补全任何字段；手工对 config 或计划任务的改动会在本步被覆盖。
   - 写入格式：UTF-8 无 BOM、`\n` 换行（带 BOM 会导致脚本读取失败；脚本已兼容 utf-8-sig，但仍以无 BOM 为准）。
6. 留痕：往 `logs/intranet-notify/` 当日文件追加一行 JSONL：`{"detectedAt", "stage": "requirement-sync", "action": "none|pending|config-written", "skillHash"}`。

## 需求台账（state/requirements.json）

```json
{
  "skillHash": "<最近处理的需求段哈希>",
  "requirements": [
    {
      "id": "req-targets | req-versions | req-scan-interval",
      "status": "待确认 | 已激活 | 已暂停 | 已被取代",
      "content": {"targets": []},
      "skillHash": "<来源需求段哈希>",
      "proposedAt": "<ISO8601>",
      "statusChangedAt": "<ISO8601>"
    }
  ]
}
```

状态机：`待确认 → 已激活 ⇄ 已暂停`；需求段变化时旧需求 → `已被取代`（终态，保留审计）。

读写约定：

- 写用原子写（写同目录临时文件再 rename）；cron 任务与 @FF 交互会话都可能写，写前必须重读最新内容。
- config 只由「已激活」需求派生；台账是唯一事实来源。

## 控制指令（@FF 交互会话专用）

群内 @FF 的消息唤起交互会话。控制指令逐字匹配（忽略 @FF 前缀与首尾空白；企微群消息会截断长文本，指令必须极简），共五个：

- **开始**：台账中「待确认」需求激活（「已暂停」同理恢复），按「需求同步」第 5 步重新生成 config 并同步 Windows 常驻守护任务，回复「已生效：」+ 需求摘要。无待确认/已暂停需求时回复当前台账状态。
- **暂停**：仅一条已激活需求时直接暂停；多条时必须「暂停 <需求ID>」，否则回复需求列表请人选。暂停后重新生成 config（移除对应内容；若暂停的是 `req-scan-interval`，常驻轮询间隔回退为 5 秒），回复「已暂停：」+ 摘要。
- **状态**：回复台账全部需求的 ID、状态、摘要；存在「待写入」草案时附带草案摘要。
- **写入**：存在「待写入」草案时，将草案内容落盘到目标文件并按「对话草案 · 草案生效路径」处理，草案标记「已写入」；无待写入草案时回复提示，不改变任何状态。
- **放弃**：将「待写入」草案标记为「已放弃」，不改动任何文件；无待写入草案时不改变任何状态。

其他任何消息：进入「对话草案」节的意图分类处理；无法解析时不改变任何状态，固定回复「我可执行：开始 / 暂停 / 状态 / 写入 / 放弃；也可直接说变更需求（如：关注版本加一个 10330011000X）或查询（如：现在监控哪些版本）」。

注意：交互会话的 cwd 是 `~/.openclaw/workspace`，操作项目文件一律用绝对路径 `C:/Users/ELadmin/Desktop/program/kimiclaw-monitor-messages/` 开头。

性能约定：每轮 MUST 用并行工具调用一次读齐所需状态（`state/requirements.json`、`state/chat-drafts.json`，按需连同本文件「采集需求」节、`config/wecom-aibot.json`），禁止串行逐文件读取；同一轮内已读过的文件 MUST NOT 重读。

## 对话草案（@FF 会话的自然语言变更入口）

非指令消息先做意图分类：**需求块修改**（targets / versions / scanInterval）、**重要性规则修改**、**运维 config 修改**、**只读查询**、**无法解析**。

- 只读查询：依据已激活需求与本文件直接回答，不生成草案、不改变任何状态。
- 无法解析：回复固定帮助文案（见「控制指令」节末）。
- 解析存在歧义（指代不明、多候选对象、缺关键参数）：MUST 只回复澄清问题，不生成草案、不改动任何文件。
- 三类变更意图：生成草案，不落盘任何文件。

### 草案文件（state/chat-drafts.json）

文件不存在视为空草案集。结构：

```json
{
  "drafts": [
    {
      "id": "draft-<时间戳>",
      "targetType": "requirements | importance-rules | ops-config",
      "rawRequest": "<人发送的原话>",
      "understanding": "<对请求的一句话理解>",
      "before": "<改前内容>",
      "after": "<改后内容>",
      "proposedAt": "<ISO8601>",
      "status": "待写入 | 已写入 | 已放弃 | 已被取代",
      "statusChangedAt": "<ISO8601>"
    }
  ]
}
```

- 同一时刻 MUST 最多一个「待写入」草案；生成新草案时，既有「待写入」草案标记「已被取代」，群内回复提示旧草案已作废。
- 草案不设时间过期；读写沿用原子写 + 写前重读约定。
- `before` 内容兼任回滚快照（见「写后校验与自动回滚」）。

### 草案回显

生成草案后群内回复 MUST 包含：对请求的理解、改前→改后对照（紧凑展示，过长截断并注明）、最终执行形态、操作指引「确认请回复：写入 / 放弃」。

### 草案生效路径（「写入」后按 targetType 分流）

- **requirements**：将 `after` 写入「采集需求」节的 ```json monitor-requirements 块（块外内容一字不动），随后立即执行「需求同步」第 1–4 步（发送需求确认消息）；激活仍须人回复「开始」。
- **importance-rules**：对「重要性判定规则」节做条目级增/删/改（MUST NOT 整节自由重写），写入即生效，回复「已生效：」+ 条目对照。
- **ops-config**：仅限「运维 config 白名单」内的文件与字段，白名单外 MUST 拒绝并提示手工修改；写入即生效，随后按白名单登记的验证方式做写后验证，回复验证结果。

### 写后校验与自动回滚

任何草案落盘后 MUST 立刻校验：

- SKILL.md：```json monitor-requirements 块可提取且 JSON 可解析，「采集需求」「重要性判定规则」等既有章节标题完好。
- config：JSON 可加载。
- 群名类变更：按「发送方式」节跑 sessions list，新群名能精确匹配到 chat_id。

校验失败 MUST：用草案 `before` 内容写回目标文件完成回滚、草案标记「已放弃」、群内报告失败原因；台账、游标等系统状态不变。

### 运维 config 白名单

可对话修改的 config 仅限下表；白名单本身的增改只能手工编辑本文件，不走对话（防止通道配置被连锁改坏后失联）。

| 文件 | 可改字段 | 写后验证 |
|---|---|---|
| `config/wecom-aibot.json` | 群名字段 | sessions list 按新群名精确匹配到 chat_id |
| `config/triage-message.txt` | 全文 | 文件非空可读 |

### 草案留痕

草案生命周期每个事件（生成 `proposed`、取代 `superseded`、写入 `applied`、放弃 `discarded`、回滚 `rolled-back`）MUST 往 `logs/intranet-notify/` 当日文件追加一行 JSONL：`{"detectedAt", "stage": "chat-draft", "action": "<事件>", "draftId", "requestDigest": "<原话前 80 字符>"}`；校验失败回滚时附 `error` 字段。

## 事件链故障告警（兜底轮职责）

py 唤醒失败时事件积压在 `state/openclaw-pending/`（json 文件，含 `detected_at`）。兜底轮检查该目录：

1. 目录为空或无文件 → 跳过。
2. 有文件且最早 `detected_at` 距今 **≤10 分钟**（一个兜底周期内，py 仍在自行重试）→ 跳过。
3. 最早 `detected_at` 距今 **>10 分钟** → 唤醒通道持续故障，按「发送方式」节向群内发一条监控自身故障告警：积压事件数、最早积压时间、处置指引（检查 gateway 是否在线、尝试手动重启）。告警不推进任何游标。
4. 防轰炸：告警后在 `logs/intranet-notify/` 当日文件追加 `{"detectedAt", "stage": "watchdog-alert", "oldestEventId": "<最早事件 event_id>"}`；后续兜底轮发现同一 `oldestEventId` 已告警过则不再重复，直到 outbox 清空后再次积压才重新告警。

## 重要性判定规则（初稿，上级可调）

> 本节只影响推送判断，改本节直接生效、无需确认闸。

**重要（触发推送）：**
- `root_files` 有新增 `.csv` 文件（added 非空）
- `root_files` 有文件被删除（removed 非空）
- 监控器自身错误：`PageValidationError`（页面结构异常，可能网站改版或被劫持）、持久化/状态写入失败、连续拉取失败、配置文件损坏（`read_config` 阶段错误）

**不重要（不推送）：**
- 无变化（无新 diff 日志）
- 单次可重试的网络抖动（`retryable: true` 且 `statePreserved: true` 的孤立超时）——但若同一 `phase` 的错误在一轮窗口内出现 ≥3 次，升级为重要
- 测试环境文件不推送

> 黑名单类文件（`*_blacklist_*.csv`）与版本类文件同等对待，不做区分；后续若上级要求区分业务优先级，改本节即可。

## 输出：聚合 markdown 模板

```markdown
**内网监控告警** <detectedAt 最新时间，YYYY-MM-DD HH:mm>
> 来源: http://172.16.30.20:8011/

【新增文件 N 个】
- `文件名1`
- `文件名2`
（超过 15 个时只列前 15 个，末尾加一行 `…另有 M 个，共 N 个`）

【删除文件 N 个】（无则省略该段）
- `文件名`

【监控错误 N 条】（无则省略该段）
- <HH:mm> [phase] errorType: message 摘要（≤80 字符）

[查看目录](http://172.16.30.20:8011/)
```

正文总长不得超过 20480 UTF-8 字节（企微上限），超出时进一步截断列表并注明。

## 发送方式（wecom 渠道，wecom-cli tool）

通过 OpenClaw 的 `wecom-cli` **tool** 发送（不是 shell 命令；禁止用 exec/curl/Python 绕过）：

1. 首次调用前按 `wecomcli-preflight` 检查工具白名单。
2. 调 `wecom-cli message aibot sessions list`，在返回中按 `chat_name` 精确匹配群名 **「未命名企业」**、`chat_type` 为 `group` 的项，取其 `chat_id`。
3. 调 `wecom-cli message aibot send --json '{"chat_id": "<上一步的 chat_id>", "msg_type": "markdown", "markdown": {"content": "<聚合正文>"}}'`。

若 `sessions list` 中找不到目标群：说明群内尚未有人 @FF 激活会话（见 `config/wecom-aibot.json` 的备注），本次按发送失败处理并留痕。

## 失败处理与游标推进

- 发送**成功**：更新 `state/notify-state.json`——`diffCursor` 推进到本轮最后处理的 diff 文件名；`errorCursor` 推进到已处理的日期与行数。
- 发送**失败**（tool 报错、找不到会话、网络异常）：往 `logs/intranet-notify/YYYY-MM-DD.log` 追加一行 JSONL：`{"detectedAt", "stage": "wecom-send", "error", "contentDigest": "<正文前 80 字符>", "pendingDiff": <待处理 diff 数>, "pendingErrors": <待处理错误数>}`；**不推进游标**，下轮重发全部积压内容。
- 判定/读取过程自身出错：同样写 `logs/intranet-notify/`，不推进游标。
