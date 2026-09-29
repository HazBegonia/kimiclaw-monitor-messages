# Spec Delta

## MODIFIED Requirements

### Requirement: Manually maintained version selection

系统 MUST 从工作区配置中读取版本选择列表；每个选择项 MUST 包含稳定的版本 ID、用于匹配目录文件名的匹配文本，以及可选的匹配模式 `mode`（`substring` 或 `fnmatch`，缺省为 `substring`）。`mode` 为 `substring` 时 MUST 按「文件名包含匹配文本」判定（等价现行为）；为 `fnmatch` 时 MUST 按 fnmatch 通配模式与完整文件名匹配判定。`mode` 取其他值时 MUST 判配置非法并走错误记录路径。配置可以包含零个、一个或多个版本。过渡期该配置文件（`config/intranet-versions.json`）MUST 由人工直接维护，作为版本选择的唯一生效来源；系统 MUST NOT 存在对该文件的自动生成或覆盖机制。

#### Scenario: Select one version

- **WHEN** 配置包含版本 ID `103300110002` 及其匹配文本
- **THEN** 系统将目录中文件名包含该匹配文本的 CSV 文件归入该版本的匹配集合

#### Scenario: fnmatch mode selection

- **WHEN** 配置项的 `mode` 为 `fnmatch`，匹配文本为 `report-*-103300110002.csv`
- **THEN** 系统将完整文件名命中该通配模式的文件归入该版本的匹配集合，仅包含该文本但不命中通配模式的文件不归入

#### Scenario: Invalid mode rejected

- **WHEN** 配置项的 `mode` 为 `substring` 与 `fnmatch` 之外的值
- **THEN** 配置加载判为非法，记录 `read_config` 阶段错误，本轮不生效

#### Scenario: Select multiple versions

- **WHEN** 配置包含多个版本选择项
- **THEN** 系统分别为每个版本计算匹配集合，不将一个版本的文件混入另一个版本的结果

#### Scenario: Empty selection

- **WHEN** 版本选择列表为空
- **THEN** 系统仍执行通用全量文件变化监控，但不生成版本快照日志

#### Scenario: Manual edit takes effect

- **WHEN** 人直接编辑 `config/intranet-versions.json` 修改版本清单
- **THEN** 下一次扫描即按新清单生成版本快照，没有任何流程会覆盖该修改
