# 现行架构

> 2026-09-22 起生效(change: share-ff-bot-connection)。运行环境为 Linux FF 服务器(172.16.30.97),systemd user services,环境细节见 `linux-deployment.md`;启停与排障见 `operations.md`。早期 Windows / OpenClaw cron 架构已退役,见 git 历史与 `openspec/changes/archive/`。

## 推送链路(纯 Python,0 token)

```
内网页面(172.16.30.20:8011)
  → 采集器 kimiclaw-monitor.service(轮询,0 token)
  → 落盘:logs/intranet-diff/(增减)、logs/intranet-focus/<版本id>/(版本快照,仅变化时)、logs/intranet-error/(JSONL)
  → 通知器 kimiclaw-notifier.service 按游标消费
  → 确定性规则判定(config/triage-rules.json,每轮热读)
  → 重要则由 src/io.py 读取 config/notify-template.json,填充并聚合一条 markdown
  → src/bot_tool.py 借 FF 智能机器人长连接直推企微群
  → 推完热重载拉活 Claw
```

## 统一输出

`src/io.py` 按功能分为三个类:`Output` 基类提供共用的 JSON 模板读取、变量替换、JSONL 日志和终端输出;`IntranetOutput` 负责内网告警模板校验、Markdown 聚合和截断;`ProgramOutput` 负责程序状态、启动、停止和错误文案。程序管理的结构化结果采用 stderr `message` + stdout JSON。采集器、通知器和程序管理器只准备业务数据;原有配置文件、日志目录、JSON 字段和企微推送方式不变。

## Claw 问答日志

通知器每轮调用 `src/io.py` 的 `ChatLogger`,读取 `~/.openclaw/agents/main/sessions/sessions.json` 识别企微会话及其历史会话,从对应 JSONL 中配对用户问题和机器人最终文本回答。按 `config/chat-log-template.json` 渲染新记录并按回答日期写 `logs/chat/YYYY-MM-DD.log`;模板每次同步热读,必须保留 `answerId` 用于去重,已有日志不改写。思考过程、工具调用和未回答问题不写入。可独立运行 `python -m src.io`,dry-run 不产生问答日志。

## 需求交互链路(claw ↔ config,2026-09-24 起)

```
上级 @FF(企微群)
  → Claw gateway(wecom 长连接,唯一需求入口)
  → skills/ff-config-assistant(草案协议:起草 → 群内回显 → 逐字「写入」→ 落盘 → 写后校验,失败自动回滚)
  → 直接改写 config/{monitors,intranet-versions,triage-rules,notifier,notify-template}.json(仅此 5 个白名单文件,其余一律拒绝)
  → py 采集器/通知器下一轮热读生效(约 10 秒,无需重启任何服务)
```

claw 与 py 链路之间**唯一接口是 config 文件**:py 代码只读不写 config,claw 不碰代码、state、密钥。白名单外需求(轮询间隔、改代码逻辑、加 schema 外字段等)直接拒绝并说明人工路径。草案台账 `state/chat-drafts.json`,留痕 `logs/intranet-notify/`(stage: `config-change`)。

已退役的旧路线(均无残留):OpenClaw cron 任务(`openclaw cron list` 为空)、监控器唤起 triage 会话(`config/triage-message.txt` 保持 0 字节)、需求台账 `state/requirements.json`(已删,备份 `state/backup-requirements-2026-09-24.json`)、事件 outbox `state/openclaw-pending/`、旧 skill `intranet-message-triage`(存档于 `wiki/`)。

## 三个 systemd 服务

| 组件         | systemd unit                        | 进程                                                                 | 职责                                                          |
| ------------ | ----------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| 采集器       | `kimiclaw-monitor.service`          | `python -m src.intranet_filename_monitor`                           | 轮询内网页面,变化/错误写日志(详见 `intranet-file-monitor.md`) |
| 通知器       | `kimiclaw-notifier.service`         | `python -m src.intranet_notifier`                                   | 游标消费 → 规则判定 → 借线推送 → 拉活 Claw                    |
| Claw gateway | `kimiclaw-openclaw-gateway.service` | `openclaw gateway run`                                               | 收上级 @FF 需求(实例 OpenClaw-oRz);**不参与推送**             |

三服务互相独立,可单独启停。unit 模板在 `scripts/linux/*.service.template`,由 `scripts/linux/install.sh` 渲染安装到新机器。

## 单 FF 错峰共用(bot_tool 编排)

FF 长连接平时归 Claw 的 wecom 插件(收 @FF 需求);`src/bot_tool.py` `push_markdown()` 借线推送:

1. 建连前记 `pendingRestore` 欠账(`state/bot-tool-state.json`);
2. 连 → 发 → 断;
3. 立刻 `openclaw config set channels.wecom.enabled --json false→true` 热重载拉活 Claw(腾讯插件被踢后故意永久挂起,只能靠 config reload 恢复);
4. 拉活失败留欠账,通知器每轮先 `ensure_companion_alive()` 补拉活;
5. 发送失败退避 5s → 30s → 5m,持久化。

**已接受代价**:推送窗口(约 30 秒)内 @FF 消息只推给 py 连接、被丢弃,服务器不补发;上级发现无回应需重发。实测结论见 `wiki/wecom-bot-connection-exclusivity.md`。

**连接独占**:同一 botId 服务端只认一条长连接——任何第三方拿 FF 凭证连接都会踢下当前持线方;不可两地同时运行整套服务(Windows 侧旧计划任务已 Disabled)。

## 规则(config/triage-rules.json,每轮热读)

- 新增/删除文件默认推;
- 监控器自身错误(`PageValidationError`、`read_config` / `write_state` / `write_snapshot_log` / `read_rules` phase)推;
- 孤立可重试抖动抑制;同 monitorId+phase 30 分钟窗口 ≥3 次升级为推送;
- 规则文件损坏 → 沿用 last-good + 群里收到「规则文件损坏」告警;
- 文件名过滤先 suppress 后 include:`suppress.filenamePatterns`(fnmatch 通配)命中的文件名判定前剔除;`push.diff.filenameIncludePatterns` 非空时只推命中的文件名;剔除总数在推送正文合并注明;schema 之外的未知字段直接判规则损坏(防「假配置」;`semantic`/`consecutiveFetchFailures` 占位字段已随 change ff-config-assistant 移除)。

## 游标:发送成功才推进

`state/notify-state.json`(`diffCursor` / `errorCursor{date,offset}`)发送成功才推进;失败写 `logs/intranet-notify/` 当日 JSONL(stage: `wecom-send`)且不推游标、下轮重试;成功写 stage: `notify-send`。

## 凭证与配置

- FF Bot ID/Secret 存 gitignored 的 `state/secrets/wecom-bot.json`;目标群 chatid 在 `config/notifier.json`。`src/.env` 只保存 DEFAULT_URL、间隔、超时、时区、日志/锁路径和渲染限制等常量。**仓库内禁止明文密钥。**
- `config/monitors.json`、`config/intranet-versions.json`、`config/triage-rules.json`、`config/notifier.json`、`config/notify-template.json` 全部热读生效。两条等价入口(2026-09-24 起,change: ff-config-assistant):人直改;或群内 @FF 提需求,经 `skills/ff-config-assistant/SKILL.md` 草案协议(起草 → 回显 → 逐字「写入」→ 落盘 → 写后校验,失败自动回滚)由 Claw 代笔,白名单外一律拒绝。`.env` 仅供人工修改,重启对应服务后生效。草案台账 `state/chat-drafts.json`,留痕 `logs/intranet-notify/`(stage: `config-change`)。

## 前置约束

- 目标群里须有人 @FF 发过消息,机器人才能主动推送;机器人被移出群再加回后需重新 @FF 并核对 chatid。
- 单实例由心跳锁保证:`state/monitor-resident.lock`、`state/notifier-resident.lock`(活锁安静退出、陈旧可接管)。

## 回滚(分钟级)

停 Linux 侧三服务后,回本机 Windows 执行 `Enable-ScheduledTask` + `Start-ScheduledTask`(`KimiclawIntranetResident` / `KimiclawIntranetNotifier` / `KimiclawOpenclawGateway`)。游标两界通用,无重复推送。
