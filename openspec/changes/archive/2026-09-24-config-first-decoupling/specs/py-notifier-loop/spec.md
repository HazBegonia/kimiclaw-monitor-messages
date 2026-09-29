# Spec Delta

## MODIFIED Requirements

### Requirement: 确定性规则判定

重要性判定 MUST 由规则文件 `config/triage-rules.json` 驱动，每轮热读（修改后下一轮生效，无需重启）；判定 MUST 只依赖产物中的结构化字段（diff 的 added/removed 文件名、错误的 monitorId/phase/errorType/retryable/statePreserved），MUST NOT 发起任何 LLM 调用。

diff 判定 MUST 先执行文件名抑制：added/removed 中命中 `suppress.filenamePatterns` 任一 fnmatch 模式的文件名 MUST 从列表中剔除后再判定；剔除后 added 与 removed 均为空的 diff 事实 MUST 判为不重要。

文件名抑制之后，若 `push.diff.filenameIncludePatterns` 非空，MUST 再执行关注过滤：added/removed 中未命中任一 fnmatch 模式的文件名 MUST 从判定与推送正文中剔除；关注过滤后 added 与 removed 均为空的 diff 事实 MUST 判为不重要。`filenameIncludePatterns` 缺省或为空列表时 MUST 不执行关注过滤（保持现行为）。关注过滤剔除的文件名数量 MUST 与抑制剔除数量采用同一口径在推送正文中注明。

文件名过滤后，added 非空与 removed 非空默认判为重要；错误按 errorType 与 phase 命中规则判为重要；未命中任何规则的事实按规则文件的 unmatched 兜底策略处理（diff 兜底为推、错误兜底为不推）。

规则文件 MUST NOT 包含未实现语义的字段：校验器遇到约定 schema 之外的未知字段 MUST 判规则文件损坏（走「规则文件自愈」路径告警），MUST NOT 静默接受；`push.diff.filenameIncludePatterns` 是约定 schema 内的可选字段，存在时 MUST 为字符串数组；`semantic` 与 `consecutiveFetchFailures` 两个历史占位字段 MUST 从 schema 与出厂 config 中移除。

#### Scenario: 规则热读生效

- **WHEN** 人在通知器运行期间修改规则文件并保存
- **THEN** 下一轮判定按新规则执行，进程未重启

#### Scenario: 新增文件判重要

- **WHEN** 新 diff 产物记录 added 非空且未命中抑制规则与关注过滤
- **THEN** 该事实判为重要，进入本轮聚合

#### Scenario: 未命中错误走兜底

- **WHEN** 一条错误记录的 errorType 与 phase 均不在规则列表中
- **THEN** 按 unmatched 兜底策略判定（默认不推送）

#### Scenario: 文件名模式抑制

- **WHEN** 规则配置 `suppress.filenamePatterns: ["*tmp*"]`，新 diff 产物 added 为 `["a-tmp-1.csv", "b.csv"]`
- **THEN** `a-tmp-1.csv` 在判定前被剔除，该事实以 added `["b.csv"]` 判为重要，推送正文中不出现被剔除的文件名

#### Scenario: 全部命中不推

- **WHEN** 规则配置 `suppress.filenamePatterns: ["*tmp*"]`，新 diff 产物 added 为 `["a-tmp-1.csv"]`、removed 为空
- **THEN** 剔除后 added 为空，该事实判为不重要，不产生推送

#### Scenario: 关注过滤只推命中项

- **WHEN** 规则配置 `push.diff.filenameIncludePatterns: ["*103300110002*"]`，新 diff 产物 added 为 `["a-103300110002.csv", "b.csv"]`
- **THEN** `b.csv` 在判定前被剔除，该事实以 added `["a-103300110002.csv"]` 判为重要，推送正文只出现命中文件名并注明剔除数量

#### Scenario: 关注过滤全空不推

- **WHEN** 规则配置 `push.diff.filenameIncludePatterns: ["*103300110002*"]`，新 diff 产物 added 为 `["b.csv"]`、removed 为空
- **THEN** 关注过滤后 added 为空，该事实判为不重要，不产生推送

#### Scenario: 关注过滤缺省保持现行为

- **WHEN** 规则文件不含 `filenameIncludePatterns` 或其为空列表，新 diff 产物 added 为 `["b.csv"]`
- **THEN** 不执行关注过滤，该事实以 added `["b.csv"]` 判为重要

#### Scenario: 未知字段判损坏

- **WHEN** 规则文件中出现约定 schema 之外的字段（如 `semantic`）
- **THEN** 校验器判规则文件损坏，通知器沿用最近一次加载成功的规则并产生「规则文件损坏」自身错误事实，群内收到告警
