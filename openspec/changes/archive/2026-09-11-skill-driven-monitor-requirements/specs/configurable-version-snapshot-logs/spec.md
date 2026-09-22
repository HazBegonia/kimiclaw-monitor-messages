## MODIFIED Requirements

### Requirement: Configurable version selection

系统 MUST 从工作区配置中读取版本选择列表；每个选择项 MUST 包含稳定的版本 ID 和用于匹配目录文件名的匹配文本。配置可以包含零个、一个或多个版本。该配置文件（`config/intranet-versions.json`）MUST 由 claw 依据需求台账中「已激活」的需求同步生成，不再作为人工直接维护的入口；手工修改 MUST 在下一次同步时被覆盖回已激活需求的推导结果。

#### Scenario: Select one version

- **WHEN** 已激活需求包含版本 ID `103300110002` 及其匹配文本，且 config 已同步
- **THEN** 系统将目录中文件名包含该匹配文本的 CSV 文件归入该版本的匹配集合

#### Scenario: Select multiple versions

- **WHEN** 已激活需求包含多个版本选择项
- **THEN** 系统分别为每个版本计算匹配集合，不将一个版本的文件混入另一个版本的结果

#### Scenario: Empty selection

- **WHEN** 已激活需求中的版本选择列表为空
- **THEN** 系统仍执行通用全量文件变化监控，但不生成版本快照日志

#### Scenario: Manual edit is overwritten

- **WHEN** 人手工向 `config/intranet-versions.json` 添加版本而 SKILL.md 采集需求段未变
- **THEN** 下一次需求同步后该文件被覆盖，手工添加的版本消失
