## Purpose

让公司能够通过配置选择一个或多个版本标识，并持续获得这些版本当前完整文件集合的可审计快照，同时保留现有通用变化检测能力。

## ADDED Requirements

### Requirement: Configurable version selection

系统 MUST 从工作区配置中读取版本选择列表；每个选择项 MUST 包含稳定的版本 ID 和用于匹配目录文件名的匹配文本。配置可以包含零个、一个或多个版本。

#### Scenario: Select one version

- **WHEN** 配置包含版本 ID `103300110002` 及其匹配文本
- **THEN** 系统将目录中文件名包含该匹配文本的 CSV 文件归入该版本的匹配集合

#### Scenario: Select multiple versions

- **WHEN** 配置包含多个版本选择项
- **THEN** 系统分别为每个版本计算匹配集合，不将一个版本的文件混入另一个版本的结果

#### Scenario: Empty selection

- **WHEN** 配置中的版本选择列表为空
- **THEN** 系统仍执行通用全量文件变化监控，但不生成版本快照日志

### Requirement: Full snapshot for selected versions

每次成功完成网页抓取和页面校验后，系统 MUST 为每个选中的版本生成一份全量快照日志；日志 MUST 包含版本 ID、扫描时间、匹配规则、匹配文件数量和该版本当前全部匹配文件名，即使本轮相较上轮没有变化。

#### Scenario: Successful unchanged scan

- **WHEN** 网页成功返回且选中版本的文件集合与上次相同
- **THEN** 系统仍为该版本生成新的全量快照日志

#### Scenario: Successful changed scan

- **WHEN** 网页成功返回且选中版本的文件集合发生新增或删除
- **THEN** 系统生成包含变化后完整文件集合的版本快照日志，并继续生成现有通用变化日志

### Requirement: Preserve generic change logs

系统 MUST 保留现有全局文件集合变化日志语义：仅当所有根级 CSV 文件集合产生新增或删除时生成变化日志；无变化时 MUST 不生成该类日志。

#### Scenario: No generic change

- **WHEN** 本轮全局 CSV 文件集合与最近一次成功快照相同
- **THEN** 系统不生成全局变化日志，但仍可生成选中版本的全量快照日志

#### Scenario: Generic change detected

- **WHEN** 本轮全局 CSV 文件集合出现新增或删除
- **THEN** 系统在通用变化日志中记录 `added` 和 `removed`，且不因版本快照功能而改变原有字段含义

### Requirement: Failure does not create snapshots

系统 MUST 将网络错误、非 HTML 响应、页面签名校验失败或不完整响应视为扫描失败；失败时 MUST 不生成版本快照日志、不生成通用变化日志，并保留最近一次成功状态。

#### Scenario: Failed scan

- **WHEN** 网页请求超时或页面校验失败
- **THEN** 系统报告本轮失败，保留最近一次成功状态，不写入任何成功扫描日志
