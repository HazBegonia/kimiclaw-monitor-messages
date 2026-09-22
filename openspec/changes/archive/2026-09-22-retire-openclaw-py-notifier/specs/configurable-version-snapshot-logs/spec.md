# configurable-version-snapshot-logs Specification (delta)

## REMOVED Requirements

### Requirement: Configurable version selection

**Reason**: 原需求中「由 claw 依据需求台账生成、手工修改在下次同步时被覆盖」的子句依赖已退役的 OpenClaw 同步链路；该行为发生根本反转（手改被覆盖 → 手改即生效），MODIFIED 无法在不丢 scenario 的前提下表达，整体移除后由新需求承载。
**Migration**: 见同文件 ADDED「Manually maintained version selection」——版本选择与匹配的全部采集语义原样保留，仅维护方式改为人工直改。

## ADDED Requirements

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
