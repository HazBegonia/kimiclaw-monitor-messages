## Purpose

让采集脚本从「只盯一个写死的 URL」变为「按配置监控多个目标页面」，换页面、加页面只改配置不改代码；配置由需求台账生成，脚本本身不理解任何业务语义。

## ADDED Requirements

### Requirement: 配置驱动多目标

系统 MUST 从 `config/monitors.json` 读取监控目标列表；每个目标 MUST 包含稳定的目标 ID、URL 及字段提取 profile；目标列表可以包含一个或多个目标。

#### Scenario: 单目标与现状一致

- **WHEN** `config/monitors.json` 只包含当前内网目录页一个目标
- **THEN** 系统对该目标的采集行为（diff 日志、错误日志、版本快照）与单 URL 现状一致

#### Scenario: 多目标并行

- **WHEN** 配置包含两个以上目标
- **THEN** 系统在一轮内依次采集各目标，任一目标失败不影响其余目标本轮的采集与日志写入

### Requirement: 目标间状态隔离

每个监控目标 MUST 拥有独立的 state 文件与 diff 日志标识（monitorId 含目标 ID）；一个目标的基线、变化与错误 MUST 不混入另一目标。

#### Scenario: 状态独立

- **WHEN** 目标 A 有文件变化而目标 B 无变化
- **THEN** 只为目标 A 生成 diff 日志，目标 B 的 state 保持不变

#### Scenario: 单目标失败隔离

- **WHEN** 目标 A 请求超时，目标 B 正常返回
- **THEN** 目标 A 记录错误日志并保留其最近成功状态，目标 B 正常完成本轮扫描

### Requirement: 配置文件错误可见

`config/monitors.json` 缺失或格式非法时 MUST 记为扫描错误（进入错误日志），且 MUST 不以任何默认目标静默替代配置目标。

#### Scenario: 配置损坏

- **WHEN** `config/monitors.json` 不是合法 JSON 或缺少必填字段
- **THEN** 本轮记录 `read_config` 阶段错误，不执行任何目标的采集
