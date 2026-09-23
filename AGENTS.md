# 任务说明

现在有 3 个信息来源，需要实时从其中抓取重要信息并实时返回到微信或者邮箱里。

信息来源：

- 公司的内部网站（通过内网）
- 企业微信消息
- 钉钉消息

消息可能有很多，有重要的或者不重要的，要过滤不重要的信息，提取出重要的。关于重要性的界定，由公司上级决定。

目前需要部署一个 agent，公司打算使用 `KIMICLAW` 来监测，需要先调研 `KIMICLAW`，然后做进一步方案。

需要调研如下：

- 1、使用 kimiclaw 的前提？
- 2、无 kimi 号（专指Allegretto计划套餐以上，能开通kimiclaw的号）有key能不能配置好kimiclaw？
- 3、kimiclaw 如何获取公司的内网 web、企业微信消息、钉钉消息的信息？
- 4、如何配置 kimiclaw？完成上述任务可行的 workflow？

目前调研完毕，写在了 wiki/KIMICLAW调研报告.md 里面。

# 最小尝试

下一步是做最小尝试调查：

~~由于缺少 kimi 会员号，经讨论决定先改用 openclaw + kimi插件 + kimi 的 key 尝试，等 kimi 号有了再换 kimiclaw。~~ 现在有 kimi 订阅号了，采用 kimiclaw 的做法。需要支持可扩展性，上级有需求变更，发给 kimiclaw，然后实时做出改变。

现在只需要做内网 web 连接测试，先不管企业微信消息和钉钉消息。

当前目标：

- 获取 http://172.16.30.20:8011/ 里面的信息；
- 获取网站里面包含 103300110002 这个字段的文件更新；

且当前目标可能会随着上级需求的变化而发生变化，功能是上级发送需求给 kimiclaw，然后做出相应改变。

目前的架构是，两个 py 脚本，一个是拿来抓取信息的，另一个是拿来连接 bot 发通知的（之前没订阅号，所以没有 claw），现在这个架构可以延续，主要是添加 kimiclaw 去和上级发生交互，然后 kimiclaw 理解需求后修改 py 脚本，做到需求更改。

需求的变化可能是：CRUD 某些新的字段或者有其它扩展需求……

<del>

## workflow

- flow1：、

  claw 通过 cron 和 py 脚本监视 web -> 监测到 web 有消息生成 .log 日志文件 -> claw 通过 skill 对消息做信息重要性处理，筛选出重要的消息 -> 企业微信

- flow2：
  py 脚本监视 web 的同时记录错误 -> py 脚本写下 .log 文件，记录异常，生成原始错误日志 -> claw 读取错误日志 -> 通过 claw 的 skill 来判断这个错误对影响业务的重要性 -> 发现重要则发送到企业微信

目前公司需要监视的内网 web 的 url 为[Directory listing for /](http://172.16.30.20:8011/)（本机可以直接访问）；

## 当前架构：py 通知器 + 单 FF 错峰共用（2026-09-22 起，change: share-ff-bot-connection）

监控链路 2026-09-18 起为 py 通知器（change: retire-openclaw-py-notifier），**0 token**；2026-09-22 OpenClaw 复活（关联 Kimi Claw 订阅号，实例 OpenClaw-oRz），与 py 通知器**错峰共用同一个 FF 机器人**。以下为现行事实，下文中所有早期章节均为历史。

- **链路**：采集器（`KimiclawIntranetResident` 任务驱动；代码改动仅限 2026-09-18 起的版本快照策略——仅在版本文件集合变化时写一条 `logs/intranet-focus/<id>/*.log`，内含改动前后两份全量清单，无变化不产生文件，取代原先每轮全量留痕）→ diff/错误日志落盘 → 通知器 `python -m src.intranet_notifier` 按游标消费 → 确定性规则判定 → 聚合一条 markdown → `src/bot_tool.py` 经 FF 智能机器人长连接直推「未命名企业」群。推送链路无 LLM。
- **通知器任务**：Windows 计划任务 `KimiclawIntranetNotifier`（登录触发 + 1 分钟守护触发器，注册：`scripts\register-windows-scheduler.ps1 -TaskName KimiclawIntranetNotifier -EntryScript run-intranet-notifier.ps1 -IntervalSeconds 5`）；runner `scripts/run-intranet-notifier.ps1` 崩溃自动重启；单实例由 `state/notifier-resident.lock` 心跳锁保证（活锁安静退出、陈旧可接管）。
- **单 FF 错峰共用（bot_tool 编排）**：FF 长连接平时归 Claw 的 wecom 插件（收上级 @FF 需求）；`src/bot_tool.py` `push_markdown()` 借线推送——建连前记 `pendingRestore` 欠账（`state/bot-tool-state.json`）→ 连→发→断 → 立刻 `openclaw config set channels.wecom.enabled --json false→true` 热重载拉活 Claw（腾讯插件被踢后故意永久挂起，只能靠 config reload 恢复）；拉活失败留欠账，通知器每轮先 `ensure_companion_alive()` 补拉活；发送失败退避 5s→30s→5m 持久化。**已接受代价**：推送窗口（约 30 秒）内 @FF 消息只推给 py 连接被丢弃，服务器不补发，上级发现无回应需重发（实测结论见 `wiki/wecom-bot-connection-exclusivity.md`）。
- **gateway 常驻任务**：Windows 计划任务 `KimiclawOpenclawGateway`（登录触发 + 1 分钟守护触发器），runner `scripts/run-openclaw-gateway.ps1`（5 秒重启循环）；日志 `logs/openclaw-gateway/YYYY-MM-DD.log` 为 **UTF-16LE**（PS5.1 重定向所致），须 `iconv -f UTF-16LE` 后再看。Claw 工作目录是 `~/.openclaw/workspace`（非项目目录）。
- **规则**：`config/triage-rules.json` 每轮热读（改后下一轮生效）；新增/删除文件默认推；监控器自身错误（PageValidationError、read_config/write_state/write_snapshot_log/read_rules phase）推；孤立可重试抖动抑制、同 monitorId+phase 30 分钟窗口 ≥3 次升级推送；规则文件损坏 → 沿用 last-good + 群里收到「规则文件损坏」告警。保留字段 `filenamePatterns`/`consecutiveFetchFailures`/`semantic` 暂不生效，等上级定义。
- **凭证**：FF Bot ID/Secret 存 gitignored 的 `state/secrets/wecom-bot.json`（复制自 `~/.openclaw/openclaw.json` channels.wecom.*，该文件保持原样作为回滚基础）；目标群 chatid 在 `config/notifier.json`（参考 `config/wecom-aibot.json`）。仓库内禁止明文密钥。
- **游标与留痕**：`state/notify-state.json`（diffCursor / errorCursor{date,offset}）发送成功才推进；失败写 `logs/intranet-notify/` 当日 JSONL（stage: wecom-send）且不推游标、下轮重试；成功写 stage: notify-send。
- **协议**：`src/wecom_bot_client.py` 按官方 `@wecom/aibot-node-sdk` 帧格式实现（wss://openws.work.weixin.qq.com；aibot_subscribe 认证 / aibot_send_msg 主动推送 / req_id 回执匹配 / disconnected_event 感知被顶），纯传输层；连接编排（借线/拉活/退避）归 `src/bot_tool.py`。同一 botId 服务端连接独占——任何第三方拿 FF 凭证连接都会踢下当前持线方。
- **调试**：`python -m src.intranet_notifier --once --dry-run`（只打印不发送不推进游标）、`--once`（单轮，失败退出码非 0）；`scripts/poc_wecom_ws.py` 单文件 PoC（实测 20480 字节上限）。
- **过渡期 config 人工维护**：`config/monitors.json`、`config/intranet-versions.json`、`config/triage-rules.json`、`config/notifier.json` 均为人工直改即生效，无自动派生/覆盖机制（需求闭环的 py 重建属后续 change）。
- **回滚（分钟级）**：`register-windows-scheduler.ps1 -Action Stop -TaskName KimiclawIntranetNotifier` 停推送即回滚推送侧；9-18 时代的「恢复 openclaw triage 链」回滚目标已不存在（cron 基建已退役，gateway 现为 Claw 需求入口而非推送方）。
- **前置约束**：目标群里须有人 @FF 发过消息机器人才能主动推送；机器人被移出群再加回后需重新 @FF 并核对 chatid。
- **openclaw 工作区残留已清（2026-09-18）**：删除 `config/openclaw-intranet-cron.json`、`scripts/register-openclaw-intranet-cron.ps1`、`scripts/register-session-compact.ps1`、`scripts/Install-OpenClaw-WeChat-PoC.ps1`、`state/openclaw-pending/`、`state/chat-drafts.json`、`state/requirements.json`、`logs/openclaw-gateway/`（2026-09-22 起该目录由 gateway 常驻 runner 重建使用）。**保留**：全局 `~/.openclaw/`（2026-09-22 起复活为 Claw 运行环境）、`state/backup-triage-message-2026-09-18.txt`（回滚备份）、`config/triage-message.txt`（0 字节禁用开关）、`config/wecom-aibot.json`（chatid 参考）。

## 发送渠道现状（2026-09-11 起 · 历史，2026-09-18 起被上方 py 通知器取代）

flow1/flow2 的"发送到企业微信"已落地：OpenClaw 官方插件 `@wecom/wecom-openclaw-plugin` 接入智能机器人 **FF**（长连接模式，不需要域名备案和可信IP），推送到测试企业「未命名企业」的全员群（李非凡在群内）。

- ~~扫描任务 `intranet-file-monitor-once` + 通知任务 `intranet-message-notify`（每分钟 agent triage+推送）~~（2026-09-14 起改为事件驱动架构，见下节）。
- 重要性判定规则见 `skills/intranet-message-triage/SKILL.md`；推送游标在 `state/notify-state.json`；推送失败记录在 `logs/intranet-notify/`。
- Bot ID/Secret 只存全局 `~/.openclaw/openclaw.json`，仓库内禁止明文密钥；群 chatId 等脱敏配置在 `config/wecom-aibot.json`。
- 前提：目标群里须有人 @FF 发过消息机器人才能主动推送；失效时重新 @FF 并核对 chatId。
- main agent 默认模型为 `kimi-coding/kimi-k2.6`；triage 唤醒、兜底轮和 @FF 交互均使用该默认模型。
- 五条控制指令继续走 LLM 会话：`message:received` hook spike 已否决，因为 hook 既不能吞掉消息，也不能主动回复企微群，若上线会产生重复回复。
- 每日计划任务 `KimiclawSessionCompact` 通过运行中的 gateway 对最近活跃的 @FF 企微群会话执行 `openclaw sessions compact --max-lines 200`；gateway 离线时只写 `logs/intranet-notify/` 的 `session-compact` 留痕，不发群消息。

## 需求驱动监控（2026-09-11 起 · 历史，2026-09-18 起冻结）

脚本退化为哑采集器（抓全量、diff、错误日志），全部判断力在 claw + SKILL.md。分工：

- **需求唯一入口**：`skills/intranet-message-triage/SKILL.md` 的「采集需求」节（监控目标 targets、关注版本 versions、扫描频率 scanIntervalSeconds）。两条等价入口：人改这一节，或群内 @FF 提出变更经草案「写入」由 claw 代笔写入（见下节「对话草案入口」）→ 兜底轮比对 skillHash → 群里发确认消息 → 人 @FF 回「开始」→ 激活并同步 config 与常驻守护任务。
- **config 由 claw 生成，禁止手改**：`config/monitors.json`（监控目标）、`config/intranet-versions.json`（版本清单）是台账的照抄产物，手工改动会被覆盖。
- **需求台账**：`state/requirements.json`（状态机：待确认 → 已激活 ⇄ 已暂停 → 已被取代）。
- **控制指令**（@FF 交互会话）：认 `开始` / `暂停` / `状态` / `写入` / `放弃` 五个逐字指令；其余消息进入对话草案的意图分类（见下节），无法解析才回固定帮助。企微群消息会截断长文本，指令必须极简。
- **多目标**：脚本读 `config/monitors.json` 循环采集；每目标独立 state（`state/intranet-files-<id>.json`），monitorId 即目标 id。
- **skill 加载**：skill 唯一位置是 `skills/intranet-message-triage/SKILL.md`；全局 `~/.openclaw/openclaw.json` 的 `skills.load.extraDirs` 指向项目 `skills/`（@FF 会话自动加载），cron prompt 按路径显式读同一文件。`.agents/skills/` 下只有 openspec 系列，勿放业务 skill。
- 全局 openclaw.json 改动后需重启 gateway 生效。
- 前提不变：gateway 需 `openclaw gateway run` 常驻，cron 与会话依赖它（但扫描不再依赖 gateway，见下节）。

## 事件驱动架构（2026-09-14 起 · 历史，2026-09-18 起被 py 通知器取代）

调度与触发从"OpenClaw cron 全包"改为"系统计划任务 + 事件驱动"：

- **扫描调度**：Windows 计划任务 `KimiclawIntranetResident` 在登录时启动 `scripts/run-intranet-monitor.ps1 -Mode Start`，默认每 5 秒轮询，0 token、不依赖 gateway。由 `scripts/register-windows-scheduler.ps1 -IntervalSeconds <2–3600> [-GuardianMinutes <1–60>]` 幂等注册，任务级 `IgnoreNew` 与 Python 心跳锁共同保证单实例；Python 异常退出后由 runner 重新拉起；runner 自身死亡由周期性守护触发器（默认 1 分钟，任务计划程序允许的最小间隔）拉起——RestartOnFailure 对 runner 级死亡实测不触发（2026-09-18 事故），runner 致命异常会写入当日 scan 日志（`=== runner fatal ... ===`）。旧的分钟任务 `KimiclawIntranetScan` 已删除；OpenClaw cron 只保留兜底通知任务。
- **事件唤醒**：py 检测到新 diff/错误日志后 spawn `openclaw agent --local --agent main -m "$(cat config/triage-message.txt)"` 唤起一次性 triage 会话；失败写入 `state/openclaw-pending/` 下轮重试，一次成功即清空队列（triage 按游标扫全量，天然幂等）。
- **兜底轮询**：cron `intranet-message-notify` 降为每 10 分钟，只做需求同步 + 事件链故障检查（outbox 积压超 10 分钟告警）+ 游标落后补扫，无动作零输出。
- **互斥锁**：triage 会话执行前取 `state/triage.lock`（15 分钟过期可打破），规则见 SKILL.md「triage 互斥锁」节。
- **运行日志**：计划任务输出落 `logs/intranet-scan/YYYY-MM-DD.log`。
- **会话生命周期**：任务为交互式登录——锁屏（Win+L）照跑（2026-09-14 实测），注销后不跑（与 gateway 同生命周期）。
- 排障要点：`openclaw agent` 必须带 `--agent main`（否则报 choose a session）；py 用 `shutil.which` 解析 openclaw.cmd（CreateProcess 不认无扩展名 shim）；含中文的 ps1 必须 UTF-8 with BOM（重写后检查文件头 EF BB BF）；PS 5.1 下原生命令 stderr 遇 EAP=Stop 会提前终止脚本（run-intranet-monitor.ps1 内已局部放开）。

## 对话草案入口（2026-09-14 起 · 历史，2026-09-18 起冻结）

群内 @FF 的自然语言变更请求不再一律回绝，改为「模型起草 + 人确认」：

- **草案流程**：变更请求 → 生成草案存 `state/chat-drafts.json`（原话/理解/改前改后/状态）→ 群内回显改前→改后对照 → 人回「写入」才落盘，「放弃」作废；同时只一个待写入草案，新草案顶掉旧的。
- **分级生效**：需求块（targets/versions/scanInterval）写入 SKILL.md 后仍走需求同步 +「开始」激活；重要性规则条目级写入即生效（禁整节重写）；白名单 config（wecom-aibot.json 群名、triage-message.txt）写入即生效 + 写后验证。
- **写后校验与回滚**：落盘后校验（需求块可解析 / config 可加载 / 群名 sessions list 可匹配），失败用草案内改前内容回滚并群内报告。
- **白名单本身只能手工改** SKILL.md，不走对话；歧义请求只追问不动笔；草案全事件留痕 `logs/intranet-notify/`（stage: chat-draft）。

约束：本机生成的任何文件都要放在 C:\Users\ELadmin\Desktop\program\kimiclaw-monitor-messages 这里，全局配置除外。

</del>
