# configurable-version-snapshot-logs Specification (delta)

## MODIFIED Requirements

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