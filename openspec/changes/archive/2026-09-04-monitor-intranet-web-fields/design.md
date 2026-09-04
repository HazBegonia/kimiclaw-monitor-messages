## Context

目标地址返回 Python `SimpleHTTP/0.6` 目录 HTML，约 1.33 MB，包含约 15,124 个根级 CSV 链接；没有 JSON、ETag、Last-Modified、SSE、WebSocket 或 Webhook。现有程序已能常驻轮询并比较文件名集合，但字段解析和 OpenClaw 事件出口尚未抽象。

## Goals / Non-Goals

**Goals:**

- 保留网页轮询边界，监控对象改为可配置字段快照。
- 默认字段为规范化后的根级 CSV 链接集合 `root_files`。
- 变化日志先持久化，再通知 OpenClaw；失败可重试。
- 防止错误页、截断页和短暂网络故障造成误删。

**Non-Goals:**

- 不访问 `172.16.30.20` 源目录。
- 不下载或解析 CSV 正文。
- 不实现服务端推送协议。
- 不处理企业微信、钉钉或 Kimi 业务规则。

## Decisions

### D1: Resident sidecar owns polling

监控程序作为一个持续运行的 sidecar，任务计划只负责启动和异常重启。OpenClaw 不使用 cron 每轮启动 agent；只有字段变化事件才唤醒 OpenClaw。

备选：由 OpenClaw heartbeat/cron 直接抓取网页。该方案仍是轮询并增加 agent 调度和模型开销，不采用。

### D2: Declarative field profiles with explicit default

增加字段配置模型，每个字段包含稳定 ID、提取类型和规范化规则。第一版只启用 `root_files`（根级链接 href，过滤目录、查询参数和非 CSV），页面 title/H1 仅作为有效性签名，不作为业务变化字段。

备选：继续硬编码 `parse_filenames`。无法扩展到其他 HTML 字段，不采用。

### D3: Canonical snapshot and atomic state

每轮成功解析后生成字段快照和 fingerprint；状态以临时文件原子替换保存。首次成功建立静默基线，后续只在 fingerprint 变化时写不可变日志。

### D4: Validate before compare

响应必须满足 HTTP 成功、HTML 内容类型、预期页面签名和完整解析；可配置最小链接数，默认拒绝异常空页。失败只记录诊断，不更新状态或生成 removed 变化。

### D5: Durable log then at-least-once event

日志成功落盘后，通过可配置的本地 Gateway HTTP 事件接口发送事件。事件包含稳定 `event_id`、监控 ID、日志路径和检测时间；失败事件写入 pending outbox 并以相同 ID 重试，接收方按 ID 幂等。

### D6: Control traffic before optimizing parser

完整页面轮询的主要成本是网络流量：5 秒约 22.9 GiB/天，1 秒约 114.9 GiB/天。实现使用流式/目标字段解析减少 CPU，但不能降低下载量；生产默认 5 秒或更长，1 秒仅用于短时测试。后续若服务方提供 manifest/version 或条件请求接口，只替换采集器。

## Risks / Trade-offs

- [轮询不是严格实时] → 在文档和事件元数据中明确准实时；严格实时需服务端推送能力。
- [页面生成中可能出现瞬态快照] → 支持可选连续确认次数或 debounce；默认保持一次成功轮询即生效。
- [Webhook 暂不可用] → 本地 pending outbox 保留事件，日志始终可人工处理。
- [字段定义可能扩展] → 通过 profile 保持解析器与事件协议稳定，新增字段不改变默认 `root_files` 语义。

## Migration Plan

1. 以新配置运行一次，建立字段快照基线，不生成日志。
2. 并行观察请求耗时、页面大小和日志变化，确认轮询间隔。
3. 配置 OpenClaw Gateway 事件地址和鉴权后启用事件投递。
4. 验证失败恢复、重复事件和 pending 重试。
5. 回滚时停止新 sidecar，保留状态、日志和 pending 目录；旧文件名监控程序可独立恢复。

## Open Questions

- OpenClaw Gateway webhook 的实际路径、鉴权头和成功响应格式需在实现前确认。
- 是否需要 `confirm_polls > 1` 以等待页面稳定，可在实现阶段通过配置决定，不改变核心协议。
