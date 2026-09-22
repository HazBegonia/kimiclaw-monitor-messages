# wecom-session-hygiene Specification

## Purpose
通过每日自动压缩 @FF 群会话（经运行中的 gateway 执行 compact，不直接改写会话文件），抑制长会话历史膨胀导致的响应劣化，且维护动作本身不产生群内噪音。
## Requirements
### Requirement: 每日会话压缩

系统 MUST 提供注册脚本创建每日一次的 Windows 计划任务，调用 OpenClaw CLI 经运行中的 gateway 对 @FF 群会话执行 compact；压缩 MUST 通过 gateway 进行，MUST NOT 直接删除或改写会话 JSONL 文件。

#### Scenario: 每日自动压缩

- **WHEN** 到达每日计划时刻且 gateway 在线
- **THEN** 群会话被 compact，历史被压缩，会话不被重置（群成员无感知、无群内消息）

#### Scenario: gateway 离线跳过

- **WHEN** 到达每日计划时刻但 gateway 不在运行
- **THEN** 本次压缩跳过并在 `logs/intranet-notify/` 当日 JSONL 留痕（stage 为 `session-compact`），不重试轰炸、不发群消息

### Requirement: 压缩任务注册幂等

重复执行注册脚本 MUST 更新既有压缩任务而不是创建重复任务。

#### Scenario: 重复注册

- **WHEN** 再次运行压缩任务注册脚本
- **THEN** Windows 计划任务中只存在一个会话压缩任务

