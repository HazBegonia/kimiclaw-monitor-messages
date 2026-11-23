# Proposal

## Why

`program/` 中的 Bash 脚本需要统一的企微查询、启动和停止入口。按用户确认的最简方案，脚本在 `program/.env` 的 `BASH` 变量中注册，管理器遍历注册项直接检查系统进程并维护日志，Claw 只负责理解请求。

## What Changes

- 从 `BASH` 环境变量读取脚本清单，支持逗号或空白分隔，也兼容 JSON 字符串数组；脚本必须位于 `program/` 内。
- `status` 遍历全部注册项，直接查询实际 Bash 进程，同时返回注册清单和运行清单。
- `start` 先检查是否运行，未运行时用 `bash` 后台启动并记录输出；已运行则不重复启动。
- `stop` 使用相同的进程查询结果停止脚本，未运行时不发送信号。
- 查询、启动、重复启动和停止写入按日 JSONL 日志；不维护 PID 状态文件。
- `templates/program-output-template.json` 定义统一输出文案，结果中的 `message` 同时用于终端和 Claw 群回复。
- 新增独立 Skill，让 Claw 通过固定 CLI 获取注册清单和操作结果，无需读取 `.env`。
- 不改变现有内网采集、通知推送和监控配置助手。

## Capabilities

### New Capabilities

- `program-control`: 通过 `.env` 的 `BASH` 注册清单、直接进程查询和操作日志，在企微对话中查询、启动和停止 Bash 脚本。

### Modified Capabilities

无。

## Impact

- 新增一个 Python 管理器及其自动化测试。
- 新增独立 Skill、按日操作日志和脚本输出日志，不新增状态目录或常驻服务。
- 更新部署、运维和 `program/` 使用说明。
- 复用现有 `python-dotenv`，不新增第三方运行时依赖。
