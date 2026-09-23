# system-scheduled-scan Specification

## Purpose

用 Windows 系统级计划任务承载内网扫描的定时调度，使采集不依赖 OpenClaw gateway 常驻；调度参数由人工经注册脚本显式维护，且任何时刻只有一个调度源在驱动扫描脚本。
## Requirements
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

### Requirement: 单调度器铁律

同一时刻 MUST 只有一个调度源驱动 py 扫描。从每分钟 tick 的计划任务迁移到常驻守护任务时，MUST 先注册并验证新任务，验证通过后再删除旧的每分钟 tick 任务；新任务验证失败 MUST 保留旧调度。

#### Scenario: 正确迁移顺序

- **WHEN** 执行调度迁移
- **THEN** 先注册常驻守护任务并手动触发验证，验证通过后才删除旧的每分钟 tick 计划任务

#### Scenario: 验证失败保留旧调度

- **WHEN** 常驻守护任务手动触发验证失败
- **THEN** 旧的每分钟 tick 计划任务仍然保留，扫描不中断

### Requirement: 扫描不依赖 gateway

系统计划任务驱动的扫描 MUST 不依赖 OpenClaw gateway 在线；gateway 停用或整体退役后，扫描与 diff/错误日志落盘 MUST 照常进行。重要性判定与推送由独立的常驻通知器（见 py-notifier-loop）承担，与采集进程互不阻塞。

#### Scenario: gateway 停机扫描继续

- **WHEN** OpenClaw gateway 停止运行
- **THEN** 计划任务照常按间隔扫描并写入 state 与日志，通知链路由通知器独立维持

### Requirement: 常驻单实例保护

常驻扫描进程 MUST 保证同一时刻至多一个实例在运行；第二个实例启动时 MUST 检测到既有实例并立即退出，不产生错误日志噪音。

#### Scenario: 重复启动自动退出

- **WHEN** 已有一个常驻扫描进程在运行，又启动第二个常驻实例
- **THEN** 第二个实例检测到既有实例后安静退出，state 与日志不受干扰

### Requirement: 暂停时安静空转

当已激活需求被暂停、监控目标为空时，常驻扫描进程 MUST 按轮询间隔安静空转（不写错误日志、不触发告警唤醒）；需求恢复激活后 MUST 在下一轮轮询自动恢复采集，无需重启进程。

#### Scenario: 暂停期间无错误噪音

- **WHEN** 全部监控目标需求处于「已暂停」状态
- **THEN** 常驻进程每轮检查 config 后安静跳过采集，`logs/intranet-error/` 不新增记录

#### Scenario: 恢复后自动采集

- **WHEN** 暂停的需求被重新激活且 config 已同步
- **THEN** 常驻进程在下一个轮询周期自动恢复扫描，不需要人工重启进程

