# system-scheduled-scan Specification (delta)

## Purpose

用 Windows 系统级计划任务承载内网扫描的定时调度，使采集不依赖 OpenClaw gateway 常驻；调度参数随需求确认自动同步，且任何时刻只有一个调度源在驱动扫描脚本。

## ADDED Requirements

### Requirement: 计划任务注册幂等

系统 MUST 提供注册脚本在 Windows 计划任务中创建或更新扫描任务；重复执行注册 MUST 更新既有任务而不是创建重复任务。任务 MUST 以项目根目录为工作目录调用扫描脚本，扫描间隔取自已激活需求（`scanIntervalMinutes`，缺省 1 分钟）。

#### Scenario: 首次注册

- **WHEN** 首次运行注册脚本
- **THEN** Windows 计划任务中存在该扫描任务，且手动触发一次能正常完成扫描并落盘 state 与日志

#### Scenario: 重复注册更新而非重复

- **WHEN** 再次运行注册脚本（参数相同或不同）
- **THEN** 既有任务被更新，系统中不出现重复的扫描计划任务

### Requirement: 需求激活驱动调度同步

需求经 @FF 确认激活后，claw MUST 调用注册脚本使计划任务与已激活需求保持一致（含扫描频率）；处于「待确认」状态的需求 MUST 不影响计划任务。

#### Scenario: 确认后同步频率

- **WHEN** 需求被确认激活且 `scanIntervalMinutes` 与当前计划任务间隔不同
- **THEN** 计划任务的扫描间隔更新为新值

#### Scenario: 未确认不动调度

- **WHEN** 需求处于「待确认」状态
- **THEN** 计划任务保持原有配置不变

### Requirement: 单调度器铁律

同一时刻 MUST 只有一个调度源驱动 py 扫描。从 OpenClaw cron 迁移到系统计划任务时，MUST 先注册并验证新任务，验证通过后再删除旧的 OpenClaw cron 扫描任务；新任务验证失败 MUST 保留旧调度。

#### Scenario: 正确迁移顺序

- **WHEN** 执行调度迁移
- **THEN** 先注册新计划任务并手动触发验证，验证通过后才删除旧的 OpenClaw cron 扫描任务

#### Scenario: 验证失败保留旧调度

- **WHEN** 新计划任务手动触发验证失败
- **THEN** 旧的 OpenClaw cron 扫描任务仍然保留，扫描不中断

### Requirement: 扫描不依赖 gateway

系统计划任务驱动的扫描 MUST 不依赖 OpenClaw gateway 在线；gateway 停顿时扫描与 diff/错误日志落盘照常进行，仅唤醒动作失败并将事件入队等待恢复。

#### Scenario: gateway 停机扫描继续

- **WHEN** OpenClaw gateway 停止运行
- **THEN** 计划任务照常按间隔扫描并写入 state 与日志，唤醒事件进入 outbox，gateway 恢复后事件被补投递
