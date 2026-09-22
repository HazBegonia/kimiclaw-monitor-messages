# configurable-version-snapshot-logs Specification

## Purpose

让公司能够通过配置选择一个或多个版本标识，并持续获得这些版本当前完整文件集合的可审计快照，同时保留现有通用变化检测能力。

## Requirements

### Requirement: Manually maintained version selection

系统 MUST 从工作区配置中读取版本选择列表；每个选择项 MUST 包含稳定的版本 ID 和用于匹配目录文件名的匹配文本。配置可以包含零个、一个或多个版本。过渡期该配置文件（`config/intranet-versions.json`）MUST 由人工直接维护，作为版本选择的唯一生效来源；系统 MUST NOT 存在对该文件的自动生成或覆盖机制。

#### Scenario: Select one version

- **WHEN** 配置包含版本 ID `103300110002` 及其匹配文本
- **THEN** 系统将目录中文件名包含该匹配文本的 CSV 文件归入该版本的匹配集合

#### Scenario: Select multiple versions

- **WHEN** 配置包含多个版本选择项
- **THEN** 系统分别为每个版本计算匹配集合，不将一个版本的文件混入另一个版本的结果

#### Scenario: Empty selection

- **WHEN** 版本选择列表为空
- **THEN** 系统仍执行通用全量文件变化监控，但不生成版本快照日志

#### Scenario: Manual edit takes effect

- **WHEN** 人直接编辑 `config/intranet-versions.json` 修改版本清单
- **THEN** 下一次扫描即按新清单生成版本快照，没有任何流程会覆盖该修改

### Requirement: Full snapshot for selected versions

每次成功完成网页抓取和页面校验后，系统 MUST 为每个选中的版本计算其当前匹配文件集合并与上次记录比较：仅当集合发生变化（含首次基线）时 MUST 生成一条版本快照日志；日志 MUST 包含版本 ID、扫描时间、匹配规则、增减计数，以及**改动前的完整文件清单**与**改动后的完整文件清单**；集合无变化时 MUST 不生成该版本的任何新日志。

#### Scenario: Successful unchanged scan

- **WHEN** 网页成功返回且选中版本的文件集合与上次相同
- **THEN** 系统不生成该版本的快照日志，也不改变该版本已记录的文件集合

#### Scenario: Successful changed scan

- **WHEN** 网页成功返回且选中版本的文件集合发生新增或删除
- **THEN** 系统生成一条版本快照日志，包含改动前的完整文件清单、改动后的完整文件清单及增减计数，并继续生成现有通用变化日志

#### Scenario: Initial baseline

- **WHEN** 版本首次被纳入监控，或状态中尚无该版本的文件集合记录
- **THEN** 系统生成一条基线快照日志，改动前清单为空、改动后清单为当前全部匹配文件

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
