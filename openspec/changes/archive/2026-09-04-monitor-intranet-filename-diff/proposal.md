## Why

当前内网服务以 HTTP 目录列表形式暴露约 15,124 个 CSV 文件。需要在不下载文件内容的前提下，尽快发现目录中文件名的新增或消失，并为每次确实发生的变化生成可供 OpenClaw 后续处理的差异日志。

## What Changes

- 新增持续运行的内网目录文件名监控能力，默认每 5 秒抓取一次目录页。
- 解析目录页中的文件名集合，只比较新增文件和消失文件。
- 首次成功扫描只建立基线，不生成 diff 日志。
- 有文件名变化时，在 `logs/intranet-diff/` 下生成带毫秒时间戳的 `.log` 文件；无变化时不创建文件。
- 使用 `state/intranet-files.json` 保存上一次成功扫描的文件名集合。
- HTTP 请求失败时保留旧状态，不将失败误判为文件删除。
- 监控过程不下载 CSV 正文、不请求单个文件元数据、不计算内容 hash。
- 为 OpenClaw 后续读取新 diff 日志预留稳定的日志格式和目录约定。

## Capabilities

### New Capabilities

- `intranet-filename-monitor`: 监控 HTTP 目录的文件名集合变化，并按约定生成新增/消失文件的 diff 日志。

### Modified Capabilities

无。

## Impact

- 新增工作区内的监控脚本、状态文件目录和 diff 日志目录。
- 依赖对 `http://172.16.30.20:8011/` 的内网访问及 VPN 连通性。
- 需要一个持续运行入口（Windows 任务计划或等效进程守护方式）。
- 不修改全局 OpenClaw provider、Kimi Key、企业微信/钉钉配置。
- 监控只产生文件名元数据，不向 Kimi 发送 CSV 内容。
