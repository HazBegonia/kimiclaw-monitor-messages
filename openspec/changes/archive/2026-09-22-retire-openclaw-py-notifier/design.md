# Design: retire-openclaw-py-notifier

## Context

现行链路：采集器（`src/intranet_filename_monitor.py`，Windows 常驻任务驱动，已实战验证）→ diff/错误日志落盘 → openclaw agent 会话按 SKILL.md 做 triage → wecom-cli tool 经 FF 推群。痛点与动机见 proposal.md。两个关键事实约束了本设计：

1. **协议证据在本地**：`~/.openclaw/npm/projects/wecom-wecom-openclaw-plugin-*/node_modules/@wecom/aibot-node-sdk/`（腾讯官方、MIT）源码完整给出长连接协议——`wss://openws.work.weixin.qq.com`、认证帧 `{cmd:"aibot_subscribe", body:{bot_id, secret}}`、心跳 `{cmd:"ping"}`、主动推送 `{cmd:"aibot_send_msg", body:{chatid, msgtype:"markdown", markdown:{content}}}`、回执按 req_id 对应、markdown 上限 20480 字节、**同一 botId 连接具有独占性（新连接顶掉旧连接）**。
2. **接口已经在跑**：logs 目录 + `state/notify-state.json` 游标（diffCursor / errorCursor{date,offset}）就是采集与判定之间现成的"持久队列 + offset"，openclaw triage 消费的正是它。通知器只是换掉消费端。

## Goals / Non-Goals

**Goals:**

- 常态全链路 0 token 的闭环：采集 → 游标消费 → 确定性判定 → 聚合 → py 直发 FF。
- 采集器**代码零改动**（仅配置停唤醒），已验证组件不引入回归。
- 每一段（解析/规则/渲染/发送）都是可替换插件点，后续变更以"加插件"接入。
- 切换可灰度、可回滚，切换前生产 FF 与 openclaw 零扰动。

**Non-Goals:**

- @FF 指令接收、需求确认闸、对话草案的任何实现（后续 change，客户端已留升级位）。
- 常驻 bot 连接与心跳（v1 按需连接，协议客户端实现 ping 帧构造但默认不使用）。
- 语义级 LLM 规则（schema 留 `semantic` 类型位，默认关闭）。
- 采集器内 openclaw 唤醒死代码的清理（保持休眠即可）。
- 新推送渠道（邮件/ webhook——Sink 插件点预留）。

## Decisions

### D1. 两个程序、一套代码，log+游标为接口（而非单进程全干）

单进程意味着改动已验证的采集器去托管通知循环。两个程序让通知器以"新写的另一半"直接闭环，采集器保持冻结；故障隔离（通知器崩→采集照跑→游标积压→恢复补扫）；将来合并只是一个部署选项（把通知循环作为线程挂进采集进程），接口不变。
*备选（否决）*：单脚本 daemon——环路未验证前先动唯一在跑的组件，风险倒挂。

### D2. 复用既有游标与留痕格式，不自造状态

`state/notify-state.json` 的 diffCursor/errorCursor、`logs/intranet-notify/` 的 JSONL 留痕、聚合 markdown 模板（20480 字节、单段 15 条截断、错误摘要 80 字符）全部原样沿用——这些语义在 triage 会话里验证过数周。回滚到 openclaw 时游标无缝续用。游标是幂等锚点：发送失败不推进 → 下轮重扫重聚合，天然"至少一次且不重复"。

### D3. bot 客户端 v1 按需连接（而非常驻心跳）

推送是低频事件（重要产物才发），v1 有消息才"连接→认证→发送→等回执→断开"，无后台线程、无重连状态机。常驻连接是接收 @FF 消息的前提，属于指令能力，留到后续 change（同一客户端类加心跳线程，非重构）。
*备选（否决）*：一上来就常驻——为不存在的接收需求引入线程与连接管理复杂度。

### D4. 规则放 `config/triage-rules.json`，每轮热读

规则 schema：`push.diff{added,removed}`、`push.errors{errorTypes[],phases[],consecutiveFetchFailures,reserve repeatEscalation{windowSeconds,threshold}}`、`suppress{isolatedRetryableError,filenamePatterns[]}`、`unmatched{diff,error}`。v1 实现集与现行 SKILL.md 规则逐条对齐：added/removed、PageValidationError、read_config/write 持久化 phases、孤立 retryable 抑制 + 窗口升级（内存计数器，~10 行，保持现行语义）。`filenamePatterns`（"测试环境文件"）与 `consecutiveFetchFailures`、`semantic` 为**保留字段**：解析进 schema、评估暂不启用，等上级给出定义后改配置即生效。
*备选（否决）*：规则块放 SKILL.md 围栏——SKILL.md 是 LLM 会话的产物，v1 消费者是 py，纯 JSON 文件对编辑器与校验更友好；重建对话草案时再议入口统一。

### D5. 规则文件自愈：last-good + 自身错误事实

规则坏 → 用上一份好规则继续判 + 产生「规则文件损坏」错误事实 → 该事实命中"监控器自身错误"规则 → 群里收到告警。规则系统用它自己的机制报告自己坏了。坏 config 由采集器 `read_config` 错误可见（既有行为），同一思路。

### D6. 协议客户端：py 实现 4 帧，依赖 `websocket-client`

认证帧、send_msg 帧、回执 req_id 匹配、超时判失败；协议细节以本机官方 SDK 源码为准绳（含 `disconnected_event` 语义）。
*备选（否决）*：Node sidecar 挂官方 SDK（多一个运行时与进程）；subprocess 调 wecom-cli（多一个二进制与独立授权）；纯 stdlib 手写 websocket（复杂度无收益）。

### D7. 凭证与目标：secrets 文件 + 可切换配置

`state/secrets/wecom-bot.json`（botId/secret，`state/` 已在 .gitignore）+ `config/notifier.json`（chatid、secrets 路径、轮询间隔、各输入路径）。PoC/影子阶段配 dev 机器人凭证与测试群 chatid；切换 = 改这两个文件，无代码差异。

### D8. 单实例与常驻任务：克隆已验证模式

心跳锁克隆 `monitor-resident.lock` 模式（`state/notifier-resident.lock`，超 2 周期可接管，活锁安静退出）。`register-windows-scheduler.ps1` 泛化 `-TaskName`/`-EntryScript` 参数（缺省值保持现有采集任务行为不变），新增 `run-intranet-notifier.ps1` runner，注册 `KimiclawIntranetNotifier` 任务（登录触发+守护触发器，与采集任务同构）。

### D9. 停唤醒走配置开关，不删代码

清空 `config/triage-message.txt`（**必须清空，不能写注释**——解析器把任何非空文本当作唤醒指令）即停用 spawn，采集器其余行为原样。死代码清理留给将来。

### D10. 切换与验证策略：dev 机器人影子先行

```
PoC(dev bot 四帧) → 影子(dry-run 日常态对照) → 切换:
  1. 停 openclaw gateway(独占连接铁律:先停后起)
  2. 清空 triage-message.txt;删 cron intranet-message-notify、KimiclawSessionCompact 任务
  3. config 切 FF 凭证与生产 chatid;注册 KimiclawIntranetNotifier;启动
  4. 观察 24h;游标推进、留痕、消息形态与影子期一致即收尾
```

首次生产启动会对游标之后的存量产物（2026-09-17 以来）补处理一次：默认让它推一条汇总（一次性补课，天然验证全链）；若不想收这条，切换前人工把游标预置到当前最新产物（操作选择，不改变设计）。

## Risks / Trade-offs

- [协议实现有 bug 或协议演进] → 以本机官方 SDK 源码为准绳，PoC+影子期用 dev 机器人实测全流程；帧面只有 4 种；SDK 开源可追。
- [切换窗口两边互踢] → 顺序铁律写入任务清单（先停 gateway 再起通知器）；影子期全部用 dev 机器人，不触碰生产 FF。
- [bot 通道故障=告警通道故障，群内无感知] → 与现状同级；发送失败每轮留痕 + scan 日志可见；邮件兜底是后续一个 Sink 插件的事。
- [窗口升级计数在内存、重启清零] → 最坏代价是升级延迟一个窗口；换来零持久化状态、零文件竞争。
- [两个计划任务=运维面×2] → 同一注册脚本、同一守护触发器模式；换来失败域隔离。
- [通知器坏→产物积压] → 游标保证恢复后无丢失；守护触发器保证进程回归。

## Migration Plan

见 D10。**回滚**（分钟级）：停 `KimiclawIntranetNotifier` 任务 → 恢复 `config/triage-message.txt` 内容（切换前留副本）→ 启动 openclaw gateway → 重新启用 cron。`~/.openclaw/openclaw.json` 全程不动；游标两界通用，回滚后 openclaw triage 从当前游标续跑，无重复推送。dev 机器人可保留作以后的测试通道。

## Open Questions

- `filenamePatterns` 的实际"测试环境"命名规范：待上级一句话定义；保留字段默认空（不抑制），不阻塞本 change。
- 切换时是否预置游标跳过存量补课：D10 已给默认（补一条），切换当天可再定。
- websocket 客户端库选型（`websocket-client` vs `websockets`）：实现期定，不影响架构。
