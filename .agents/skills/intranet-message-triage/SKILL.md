---
name: intranet-message-triage
description: 内网监控消息的重要性判定与企业微信推送。当一轮内网扫描完成后，读取 logs/intranet-diff/ 与 logs/intranet-error/ 的新增产物，判定重要性，将重要消息聚合成一条 markdown 通过企微 FF 机器人（wecom 渠道）推送到全员群，并推进 state/notify-state.json 游标。
user-invocable: true
---

# 内网监控消息重要性判定与推送（flow1 / flow2 末端）

每轮监控扫描完成后执行一次本流程。三条铁律：

1. **不重要的不发，无变化的不发** —— 群里只出现值得李非凡看的消息。
2. **一轮最多一条推送** —— 本轮所有重要内容聚合为一条 markdown（企微频控 30 条/分钟、1000 条/小时/会话，聚合后远低于限额）。
3. **发送成功才推进游标** —— 失败留痕、下轮重试，不允许静默丢消息。

## 输入

| 来源 | 位置 | 格式 |
|---|---|---|
| flow1 变更日志 | `logs/intranet-diff/*.log` | 类 YAML：`detectedAt`、`changedFields: - root_files: {"added": [...], "removed": [...]}` |
| flow2 错误日志 | `logs/intranet-error/YYYY-MM-DD.log` | JSONL，每行字段：`eventId` `detectedAt` `phase` `errorType` `message` `statePreserved` `retryable` |
| 推送游标 | `state/notify-state.json` | `{"diffCursor": "<已处理到的 diff 文件名>", "errorCursor": {"date": "<日期>", "offset": <已处理行数>}}` |

只处理**游标之后**的新产物：diff 按文件名（时间戳）排序取 `diffCursor` 之后的 `.log`；error 取当日文件 `offset` 行之后的新行（跨天则从 `errorCursor.date` 之后的日期文件第 0 行开始）。

## 重要性判定规则（初稿，上级可调）

**重要（触发推送）：**
- `root_files` 有新增 `.csv` 文件（added 非空）
- `root_files` 有文件被删除（removed 非空）
- 监控器自身错误：`PageValidationError`（页面结构异常，可能网站改版或被劫持）、持久化/状态写入失败、连续拉取失败

**不重要（不推送）：**
- 无变化（无新 diff 日志）
- 单次可重试的网络抖动（`retryable: true` 且 `statePreserved: true` 的孤立超时）——但若同一 `phase` 的错误在一轮窗口内出现 ≥3 次，升级为重要

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
