# Wiki Log

## 2026-09-22 · 守护任务重建后的「不间断终端弹窗」事故

- 现象：Claw 响应群内「增加 103300110009 监视」需求时重建了 `KimiclawIntranetResident` 任务，之后每分钟弹一次 PowerShell 终端窗口。
- 根因：Claw 的「重建并重启」= Stop-ScheduledTask + 重新注册。**Stop-ScheduledTask 只杀 runner（powershell），不杀它拉起的 python 子进程**——9-18 启动的旧 python 带着心跳锁继续存活。新守护触发器每分钟点火 → 新 runner 看到活锁安静退出（exit 0）→ 每分钟一次进程启动 = 每分钟一次控制台窗口闪现（`-WindowStyle Hidden` 只能隐藏窗口主体，conhost 创建瞬间的闪现避免不了）。
- 修复：杀掉孤儿 python（PID 25384）→ 任务重新点火 → python 18076 接管锁、runner 常驻 → 守护点火恢复静默空操作（IgnoreNew 不启进程）。观察 4 分钟 run-start 零增长确认止血。
- 教训：① 停 `KimiclawIntranetResident` 时必须同时杀掉 `intranet_filename_monitor` 的 python 进程，否则必然进入每分钟弹窗状态；② 不要在常驻链健康时手工跑 `python -m src.intranet_filename_monitor` 做诊断——它可能接管心跳锁然后退出，造成锁易手动荡（本次修复期间的 PID 抖动就是诊断命令自己引入的）；③ 健康判据：任务 State=Running + 锁心跳新鲜 + 当日 scan 日志 run-start 计数不增长。

## 2026-09-22 · share-ff-bot-connection 实施完成

- 决策推翻同日早些时候的「双机器人」方案（见下条）：用户拍板**单 FF 错峰共用**——推送窗口消息丢失的代价可接受，省一个机器人。wiki 决议页 [wecom-bot-connection-exclusivity](wecom-bot-connection-exclusivity.md) 已整体改写为现行方案。
- 新增 `src/bot_tool.py` 可扩展工具层接管推送编排：建连前记 `pendingRestore` 欠账（`state/bot-tool-state.json`，原子写、损坏自愈）→ 连→发→断 → 立刻 `openclaw config set channels.wecom.enabled --json false→true` 触发热重载拉活 Claw；拉活失败留欠账，通知器常驻循环每轮先 `ensure_companion_alive()` 补拉活。发送失败退避 5s→30s→5m 持久化。预留 `dump_inbox()` 扩展位。`src/intranet_notifier.py` 推送路径改走 `bot_tool.push_markdown()`，游标语义不变。测试 94 全绿（新增 `tests/test_bot_tool.py` 15 例）。
- gateway 常驻化：新计划任务 `KimiclawOpenclawGateway`（登录触发 + 1 分钟守护触发器），runner `scripts/run-openclaw-gateway.ps1`（纯英文无需 BOM，5 秒重启循环，日志 `logs/openclaw-gateway/`），杀进程实测 5 秒内自愈。`channels.wecom.enabled` 恢复 true，Claw 持 FF 长连接。
- 踢线演练结论：① py 推送实发成功，Claw 被踢后 27 秒内被拉活，无互踢循环；② config 热重载只重启 wecom 通道，kimi-claw 桥无感；③ **窗口消息服务器不补发**——py 占线 90 秒期间的 `@FF hi` 推到 py 连接被丢弃，Claw 重连后收不到；④ Claw 被踢前一刻收到的消息，agent 回复时连接已断（`WSClient not connected`），群里表现为无回应。
- 排障注意：gateway 日志是 UTF-16LE（PS5.1 `*>>` 重定向所致），须 `iconv -f UTF-16LE` 后再 grep。

## 2026-09-22 · 旧 OpenClaw 关联 Kimi Claw（relink）

- 本机旧 OpenClaw（2026.7.1-2）通过 kimi-claw 桥插件（v0.27.1）关联到 Kimi 账号，实例名 OpenClaw-oRz，端到端对话验证通过。桌面端「关联已有 OpenClaw」弹窗的一行命令不可直接跑：其并行执行的 kimiim-cli 子脚本仅支持 Linux/macOS（Windows 必败），只跑主脚本 `cdn.kimi.com/kimi-claw/install.sh --bot-token <token>` 即可。
- 凭证教训：bot-token 从截图 OCR 抄错两个字符（`5goln`→`5goIn`、`5pgpc`→`5pggc`），服务器回 401 bot not found；**凭证必须用复制按钮拿文本，不可 OCR 截图**。
- 全局 `~/.openclaw/openclaw.json` 变更：换新 kimi-coding API key；主模型由已下线的 `kimi-k2.6` 改为 `kimi-for-coding`（端点现存模型：kimi-for-coding / kimi-for-coding-highspeed / k3 / k3-256k）；`channels.wecom.enabled=false`（FF 凭证，防与 py 通知器抢长连接）；`openclaw-weixin` 插件禁用。改前备份 `openclaw.json.bak-relink-20260922-140919`。
- ~~决策：企微侧采用双机器人~~（同日被单 FF 错峰共用取代，见上条）。
- 待办：~~gateway 常驻~~（已注册 `KimiclawOpenclawGateway`，见上条）；Claw 工作目录是 `~/.openclaw/workspace`（非项目目录），需求闭环契约里要写明项目路径 `C:\Users\ELadmin\Desktop\program\kimiclaw-monitor-messages`。
- 小瑕疵：gateway 日志报 `spawn openclaw ENOENT`（插件在 gateway 进程里调 CLI 取版本号失败，Windows 无扩展名 shim 老问题），仅影响元数据上报。

## 2026-09-18 · optimize-monitor-latency 验证与事故修复

- 验证发现监控空窗约 17 小时：昨 17:57 注销后停止，今 10:28 登录触发的 runner 静默死亡、RestartOnFailure 未重试（杀进程复现确认：RestartOnFailure 对 runner 级死亡不触发，任务 XML 配置无误）。修复：runner 主体加 try/catch，致命异常写当日 scan 日志（`=== runner fatal ... ===`）后 exit 1；注册脚本新增周期性守护触发器（`-GuardianMinutes`，默认 5 分钟，IgnoreNew 下运行中为空操作，任务死亡后下一周期自动拉起）。已通过「杀 runner+python → 守护触发器 11:41 自动拉起」实测。
- `config/triage-message.txt` 昨 17:14 被清空成 0 字节（未跟踪、无历史），导致事件唤醒整体静默失效。从 09-14 的唤醒会话记录中找回原文并恢复；注意 triage 消息只在 python 启动时加载，改后需重启常驻任务生效。
- Kimi 周配额昨 15:25 起耗尽：兜底 cron `intranet-message-notify` 连续 8 次报错后被停用（enabled=0），12:17 探测确认配额已恢复。cron 的启停经 gateway 操作，gateway 当前未运行——恢复后需 `openclaw cron enable intranet-message-notify`。
- 台账三条需求（targets/versions/scanIntervalSeconds=5）自昨 17:45 起「待确认」，确认消息已发测试群但无人回「开始」（任务 7.2 仍待走通）。
- C2 hook delta spec 已从 change 中移除（spike 否决的需求不应归档进主 spec）；`docs/workflow.md` 顶部加过时声明，skill 路径修正为 `skills/`。
- 排障注意：本机 TaskScheduler/Operational 事件日志是禁用的，启用需管理员（`wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`）；WMI 按命令行搜进程时查询进程自身会误匹配（自身 cmdline 含关键词），需排除。

## 2026-09-17 · optimize-monitor-latency 实施

- main agent 已切换到 `kimi-coding/kimi-k2.6`；验证过的 provider 配置保持在全局 OpenClaw 配置中，不写入仓库。
- `message:received` hook spike 被否决：hook 不能阻止消息继续进入 LLM 会话，也不能主动向企微群回复，因此五条控制指令仍由 LLM 会话处理。
- 扫描迁移到 Windows 常驻任务 `KimiclawIntranetResident`。任务在登录后以隐藏 PowerShell 运行，5 秒轮询，Python 心跳锁防止重复实例；实测强制结束 Python 后 runner 在锁失效后重新拉起新实例。旧的 `KimiclawIntranetScan` 分钟任务已删除。
- 新增每日 `KimiclawSessionCompact` 任务。它通过 gateway 压缩最近活跃的企微群会话，使用 `--max-lines 200` 保持任务时长可控；gateway 离线时只留痕。
- 「采集需求」字段改为 `scanIntervalSeconds: 5`。新的 targets、versions 和扫描间隔需求已发往测试群等待确认；群成员 @FF 回复「开始」后，才能把这轮需求激活并由需求同步重建守护任务。

## 2026-09-11 · wecom-aibot-notify 实施完成

- 安装 `@wecom/wecom-openclaw-plugin`，以智能机器人 FF（长连接）建立企微渠道；Bot ID/Secret 入全局 `~/.openclaw/openclaw.json`。
- 凭证排障：Secret 从截图 OCR 得到 `28Qn0w`（数字0），正确为 `28QnOw`（字母O），errcode 853000；另需机器人创建者在「工作台-智能机器人」授权「消息」权限（errcode 850002），授权后 `sessions list` 可用。
- 会话激活：李非凡在全员群 @FF 后发一条消息，取得群 chatId，存 `config/wecom-aibot.json`（脱敏）。
- 补全 `.agents/skills/intranet-message-triage/SKILL.md`（判定规则、聚合模板、游标/失败处理）；`register-openclaw-intranet-cron.ps1` 新增注册 `intranet-message-notify` agent 任务（每 1m）。
- 端到端验证：首轮推送 80 个新增 csv 的聚合告警；3 条同 phase 拉取错误触发错误告警；空闲轮次不推送；游标正常推进。
- 注意：PowerShell 脚本必须保持 UTF-8 with BOM（编辑器重写后需检查文件头 EF BB BF）。

## 2026-09-14 · event-driven-monitoring 实施

- 架构切换：OpenClaw cron 每分钟 agent triage（估算 3000-6000 万 token/天）→ 事件驱动：Windows 计划任务 `KimiclawIntranetScan` 每分钟扫描（0 token）+ py 检测到新 diff/错误日志后 spawn `openclaw agent --local --agent main` 唤醒 triage + 兜底 cron 降频 10 分钟（需求同步/事件链检查/游标扫尾）。
- 关键坑：① `openclaw agent --local -m` 必须带 `--agent main`（否则报 "Pass --to/--session-key/--session-id/--agent"）；② py Popen 要用 `shutil.which("openclaw")` 解析到 openclaw.cmd（CreateProcess 不试 PATHEXT，无扩展名 shim 会 WinError 2）；③ PS 5.1 下原生命令 stderr 遇 ErrorActionPreference=Stop 触发 NativeCommandError 提前终止（脚本内局部改 Continue）；④ Edit 工具重写 ps1 会丢 UTF-8 BOM，含中文脚本改后必须检查文件头。
- 演练记录：gateway 停机约 3 天期间计划任务照跑、diff 检出、事件入队 outbox；恢复后自动补投递、清空队列、推送 24 个新文件聚合告警。互斥锁演练：持锁时触发的 triage 会话直接退出，游标未动、锁未被误删。兜底轮在事件链故障期间按规则发出 watchdog-alert。
- 已知小瑕疵：发生 spawn 的轮次里 run-intranet-monitor.ps1 的 run end 行可能缺席（detached 子进程与输出重定向的句柄耦合），不影响功能。

## 2026-09-14 · chat-driven-skill-config-editing 实施

- 对话草案入口上线：群内 @FF 自然语言变更请求 → 草案（`state/chat-drafts.json`，含原话/理解/改前改后）→ 群内回显对照 →「写入」落盘 → 写后校验。指令集扩为 开始/暂停/状态/写入/放弃；分级生效：需求块仍要「开始」激活，重要性规则条目级写入即生效，白名单 config（wecom-aibot.json 群名、triage-message.txt）写入即生效+写后验证。
- 演练记录：需求块双向（加/删 103300110009）全链路通过；规则条目写入生效；群名改成不存在群 → sessions list 验证失败 → 自动回滚且通道不断；取代/放弃/追问/只读查询行为正确；留痕覆盖 proposed/superseded/applied/discarded/rolled-back。
- 关键坑：@FF 群会话是长会话，skill 只在会话创建时加载——改完 SKILL.md 必须重置群会话（停 gateway → 移走 `~/.openclaw/agents/main/sessions/<id>.jsonl` 及索引项 → 重启）才生效，否则 bot 按旧规则应答。另：`os.replace` 在 gateway 存活时对 sessions.json 会因文件锁失败（WinError 32），须先停 gateway 或原地写。
- 已知小瑕疵：① agent 手写留痕 JSONL 偶有格式错误（15:18 出现一行反斜杠乱写），后续可考虑把留痕固化成脚本；② SKILL.md 新增「性能约定」（并行一次读齐状态、禁重读）只对新建会话生效。
