# system-scheduled-scan Specification (delta)

## MODIFIED Requirements

### Requirement: 计划任务注册幂等

系统 MUST 提供注册脚本在 Windows 计划任务中创建或更新扫描任务；重复执行注册 MUST 更新既有任务而不是创建重复任务。任务 MUST 以项目根目录为工作目录调用扫描脚本；扫描间隔作为注册脚本的显式参数维护（缺省保持当前常驻轮询间隔 5 秒），不再由需求台账推导。

#### Scenario: 首次注册

- **WHEN** 首次运行注册脚本
- **THEN** Windows 计划任务中存在该扫描任务，且手动触发一次能正常完成扫描并落盘 state 与日志

#### Scenario: 重复注册更新而非重复

- **WHEN** 再次运行注册脚本（参数相同或不同）
- **THEN** 既有任务被更新，系统中不出现重复的扫描计划任务

#### Scenario: 崩溃自动重启

- **WHEN** 常驻扫描进程异常退出
- **THEN** 计划任务/runner 自动重新拉起常驻扫描，无需人工干预

#### Scenario: runner 死亡后守护触发器拉起

- **WHEN** 常驻守护任务的 runner 进程死亡、任务实例结束（无论是否触发失败重启）
- **THEN** 周期性守护触发器在下一个周期自动重新启动任务，常驻扫描恢复，无需人工干预

### Requirement: 扫描不依赖 gateway

系统计划任务驱动的扫描 MUST 不依赖 OpenClaw gateway 在线；gateway 停用或整体退役后，扫描与 diff/错误日志落盘 MUST 照常进行。重要性判定与推送由独立的常驻通知器（见 py-notifier-loop）承担，与采集进程互不阻塞。

#### Scenario: gateway 停机扫描继续

- **WHEN** OpenClaw gateway 停止运行
- **THEN** 计划任务照常按间隔扫描并写入 state 与日志，通知链路由通知器独立维持

## REMOVED Requirements

### Requirement: 需求激活驱动调度同步

**Reason**: 需求确认闭环依赖 OpenClaw 会话（@FF 指令、claw 调用注册脚本），随 openclaw 整体退役暂停，调度参数不再有自动同步来源。
**Migration**: 扫描间隔由人工经注册脚本参数维护（「计划任务注册幂等」要求继续生效）；需求闭环的 py 重建由后续 change 承载，届时恢复自动同步。
