## 1. 环境与 PoC（dev 机器人先行）

- [x] 1.1 ~~新建 dev 智能机器人…~~（2026-09-18 用户决定**跳过 dev 机器人、直接用 FF** 测试并立即停 openclaw；连接独占/先停后起顺序已在生产切换中实测，无互踢）
- [x] 1.2 编写 `scripts/poc_wecom_ws.py` 单文件 PoC：连接 wss → 认证帧 → `aibot_send_msg` 推一条 markdown 到 dev 测试群 → 关闭；实测回执语义与 20480 字节上限（已用 FF 生产凭证实测认证+回执+推送成功；20480 上限由 PoC 脚本提供，未在生产发超限探测）
- [x] 1.3 安装 py 依赖 `websocket-client`，确定版本并记录到项目文档

## 2. 机器人客户端（src/wecom_bot_client.py）

- [x] 2.1 实现协议客户端：连接/认证帧、回执按 req_id 匹配、超时与错误分类、关闭；`send_markdown(chatid, content)` 返回明确的成功/失败（对照本机官方 SDK 源码核对帧格式）
- [x] 2.2 单元测试：帧构造、回执匹配、超时判失败、认证失败可见（mock 连接）

## 3. 规则引擎（src/triage_rules.py + config/triage-rules.json）

- [x] 3.1 编写 `config/triage-rules.json` 初版：现行 SKILL.md 规则机器化（push.diff.added/removed；errors.errorTypes=[PageValidationError]、phases=[read_config, write_state, write_snapshot_log]；suppress.isolatedRetryableError；repeatEscalation={windowSeconds:1800, threshold:3}；unmatched 兜底）；保留字段 filenamePatterns/consecutiveFetchFailures/semantic 置默认不启用
- [x] 3.2 实现规则加载与校验：每轮热读、last-good 自愈、坏文件产生「规则文件损坏」自身错误事实
- [x] 3.3 实现评估纯函数：diff 事实判定、错误事实判定（孤立抖动抑制 + 同 monitorId/phase 窗口升级内存计数）
- [x] 3.4 单元测试：现行规则逐条映射用例、坏规则自愈用例、窗口升级用例

## 4. 通知器主程序（src/intranet_notifier.py）

- [x] 4.1 游标读写：沿用 `state/notify-state.json` 格式（diffCursor / errorCursor{date,offset}），缺失视为空游标，原子写
- [x] 4.2 产物收集与解析：diff 日志（monitorId/detectedAt/added/removed）、错误 JSONL（日期+行偏移，含跨天从第 0 行）
- [x] 4.3 聚合渲染：沿用既有模板（来源行/新增段/删除段/错误段/目录链接；单段 15 条截断+剩余数；错误摘要 ≤80 字符；正文 ≤20480 UTF-8 字节）
- [x] 4.4 主循环编排：单实例锁 → 收集 → 判定 → 无重要则静默推游标；有重要 → 渲染 → 客户端发送 → 成功推游标 / 失败写 `logs/intranet-notify/` 当日 JSONL 留痕且游标不动
- [x] 4.5 CLI：`--once`（单次+非零退出码）、`--interval`、`--dry-run`（打印不发送、不推游标）
- [x] 4.6 单元测试：tmp 目录造产物跑全循环——增量消费、失败留痕与重试不重复、跨天消费、dry-run、单实例锁（活锁退出/陈旧接管）

## 5. 常驻任务

- [x] 5.1 泛化 `scripts/register-windows-scheduler.ps1`：新增 `-TaskName`/`-EntryScript` 参数，缺省值保持现有采集任务行为；回归验证采集任务注册不受影响（UTF-8 BOM 保持）
- [x] 5.2 新增 `scripts/run-intranet-notifier.ps1` runner（崩溃重启循环，同采集 runner 模式）
- [x] 5.3 注册 `KimiclawIntranetNotifier` 任务并验证：双实例互斥、杀进程后守护触发器拉起、无可见窗口

## 6. 影子验证（dev 机器人，生产零扰动）

- [x] 6.1 ~~通知器以 dev 凭证+测试群 chatid 常驻运行，`--dry-run` 与真实 dev 推送并行观察若干天~~（用户决定直接用 FF：影子期并入生产，观察由 7.4 承担）
- [x] 6.2 对照检查：消息形态、聚合与截断、游标推进、失败留痕均与预期一致；按观察结果修订规则初值（补课推送已对照 dry-run 与真实推送一致；09-18~09-22 观察期 11 次真实推送形态/聚合/游标均正常，规则初值无需修订）
- [x] 6.3 全套测试通过：`python -m pytest tests/ -q`（含既有采集器测试零回归，78 passed）

## 7. 切换生产（顺序铁律：先停 gateway 再起通知器）

- [x] 7.1 备份 `config/triage-message.txt` 内容；确认 `~/.openclaw/openclaw.json` 全程不动
- [x] 7.2 停 openclaw gateway → 清空 `config/triage-message.txt`（清空而非注释）→ 删除 cron `intranet-message-notify` 与计划任务 `KimiclawSessionCompact`
- [x] 7.3 `config/notifier.json` 切 FF 凭证与生产群 chatid（对照 `config/wecom-aibot.json` 参考值）；首次启动观察存量补课推送（或预置游标跳过，切换当天定）
- [x] 7.4 观察 24 小时：推送、游标、留痕正常；确认 openclaw 全停后无连接互踢迹象（2026-09-22 核：09-18 切换后 11 次 notify-send 全部成功、0 失败，diffCursor 推进至当日最新；两守护任务 Running；无 openclaw 进程残留，无互踢迹象）

## 8. 文档与收尾

- [x] 8.1 更新 `AGENTS.md`（发送渠道现状/事件驱动架构/需求驱动监控各节改为 py 通知器架构；记录过渡期 config 人工维护）
- [x] 8.2 更新 `docs/intranet-file-monitor.md` 与 `docs/workflow.md`（新增通知器章节；旧 cron/会话流程标注为历史）
- [x] 8.3 `skills/intranet-message-triage/SKILL.md` 顶部标注退役与规则迁移去向（不删文件，保留需求节与审计价值）
- [x] 8.4 归档 openspec change `optimize-monitor-latency`（其剩余任务 7.2 随链路替换失效）；`openspec validate retire-openclaw-py-notifier --strict` 通过
- [ ] 8.5 整理并提交本 change 的 git 改动（工作区尚有既有未提交历史，分开提交，不混入本 change）——**用户承担**（明确要求不动 git）
