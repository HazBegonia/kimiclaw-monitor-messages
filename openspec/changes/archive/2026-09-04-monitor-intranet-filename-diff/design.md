## Context

目标服务是 Python `SimpleHTTP/0.6` 标准目录列表，当前目录约 15,124 个 CSV 文件，目录页约 1.33 MB。服务端没有文件变化推送接口，因此客户端只能通过重复 GET 目录页实现约 5 秒级准实时检测。详见 proposal.md 和 `specs/intranet-filename-monitor/spec.md`。

## Goals / Non-Goals

**Goals:**

- 以文件名集合 diff 实现低延迟变化检测。
- 无变化时零 diff 文件写入；有变化时生成可排序、Windows 安全的时间戳日志。
- 网络或解析失败不造成误删判断。
- 监控过程不下载 CSV 内容。

**Non-Goals:**

- 不检测已有文件内容、大小或修改时间变化。
- 不实现服务端 WebSocket/SSE 推送。
- 不负责企业微信/邮箱投递或重要性判断。

## Decisions

### D1: Continuous process with configurable polling

采用持续运行的监控进程，默认每 5 秒 GET 一次目录页，而不是依赖每轮启动的 OpenClaw agent。理由是当前 HTTP 服务不支持推送，且持续进程可避免调度启动开销；轮询间隔可在负载较高时调大。Windows 任务计划用于启动和守护该进程。

备选：OpenClaw cron 每 5 秒启动一次命令。该方式调度开销大、可靠性差，不采用。

### D2: Set comparison from directory HTML

每轮只解析目录页中的文件链接，过滤目录链接、查询参数和片段，并以规范化文件名组成集合。使用集合差集计算 `added = current - previous` 与 `removed = previous - current`。

备选：逐文件 HEAD 或下载内容。它们无法改善文件名集合检测，且会显著增加请求或数据暴露，不采用。

### D3: State and log persistence

状态保存为工作区内的 `state/intranet-files.json`，仅保存最近一次成功扫描的排序文件名集合和扫描时间。状态与日志采用临时文件写入后原子替换，避免进程中断留下半写文件。只有 diff 非空时才创建 `logs/intranet-diff/` 下的日志。

备选：每轮无条件重写状态或使用 SQLite。当前只有一个集合且只在变化时持久化，JSON 足够简单；若未来出现多监控源或并发写入，再迁移 SQLite。

### D4: Windows-safe timestamp naming

日志名使用 `yyyy-MM-dd_HH-mm-ss-fff.log`，不用冒号以满足 Windows 文件名约束。正文使用 Asia/Shanghai 时间并包含 `+08:00`；同一毫秒冲突时追加递增序号。

### D5: OpenClaw consumes batches, not every poll

监控进程只负责生成 diff 日志。OpenClaw 以较低频率读取新日志并批量摘要；没有新日志时不触发 Kimi，避免空调用和不必要额度消耗。

## Risks / Trade-offs

- [轮询不是真正服务端推送] → 默认 5 秒间隔并明确“准实时”；若需严格实时，未来增加服务端 SSE/WebSocket 或共享文件系统事件源。
- [目录页较大] → 只传输目录 HTML，不请求单个 CSV；轮询间隔可配置并支持退避。
- [短暂新增后又消失的文件可能被漏检] → 这是轮询模型的固有限制；严格捕获需服务端事件流。
- [网络中断导致检测延迟] → 失败时保留基线，恢复后与最近成功集合比较。

## Migration Plan

1. 部署监控程序和工作区状态/日志目录。
2. 手动运行一次确认可访问内网目录；首次运行只建立基线。
3. 通过 Windows 任务计划设置登录启动和异常重启。
4. 观察 diff 日志和请求负载，再调整轮询间隔。
5. 回滚时停止任务计划并保留或移走状态、日志目录；不触碰 OpenClaw 全局配置。
