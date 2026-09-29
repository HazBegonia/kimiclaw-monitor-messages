# Design

## Context

动机见 proposal.md。当前形态：`src/triage_rules.py` 的 `_ALLOWED_KEYS` 封闭 schema + `evaluate_diff`/`filter_diff_fact` 只有 suppress（排除）过滤；`src/intranet_filename_monitor.py` 的 `filter_version_files` 用 `v["match"] in name` 子串匹配；`DEFAULT_RULES` 与出厂 `config/triage-rules.json` 内容重复。通知器与采集器均每轮热读 config，新键落盘下一轮生效，无重启成本。

## Goals / Non-Goals

**Goals:**

- include 维度（只关注）与版本 `mode` 进入封闭 schema，校验、判定、测试、skill 能力表四者同步。
- 现有 config 文件不加新键也能通过校验、行为不变（向后兼容）。
- `DEFAULT_RULES` 收窄为最小自愈集，业务默认值只留在出厂 config。

**Non-Goals:**

- 不做通用规则解释器/DSL（见 Decisions 的 D3）。
- 不改求值优先级结构、不改 markdown 渲染模板。
- 不引入 regex 匹配模式（fnmatch 已覆盖现有可预见需求）。

## Decisions

### D1: include 过滤的位置与口径

`filenameIncludePatterns` 放在 `push.diff` 下（而非 `suppress` 旁），因为它是「什么算重要」的判定条件，不是「什么算噪音」的抑制。执行顺序：**先 suppress 剔除，再 include 过滤**——suppress 语义是「这些文件永远不算数」，优先级高于关注名单。两种过滤剔除的数量合并进同一个正文注释（沿用现有「已按规则忽略 N 个匹配文件名」口径），不新增渲染分支。

替代方案：把 include 做成 `suppress.filenameExcludePatterns`（排除的反面）。否决：语义绕（双重否定），且上级提需求时的自然说法是「只推带 X 的」，正向 include 与需求语言对齐。

### D2: `mode` 默认 substring，非法值判配置损坏

`load_selected_versions` 校验 `mode ∈ {substring, fnmatch}`，缺省补 `substring`。非法值抛错走 `read_config` 错误路径（与现有「targets 非法」同路径），群内经通知器收到告警。不做「非法 mode 降级为 substring」——静默降级会制造配置与人理解不一致的假生效。

替代方案：直接让 `match` 支持 fnmatch 语法自动探测（含 `*` 就当通配）。否决：隐式语义不可预测，文件名里合法出现 `*` 的场景虽罕见但行为分叉无法告警。

### D3: 本变更不做规则解释器，立「config 优先」决策规则代替

完整 DSL（条件→动作规则表 + 封闭算子词表）能彻底冻结 src，但前期成本（引擎重写 + 测试矩阵重写 + v1/v2 双格式迁移）与当前需求频率不匹配。改为项目惯例：**新需求先问能否表达为现有 config 的一个新键；能则加键（一次性 src 小改）；同类需求第二次出现且加键开始组合爆炸时，再立项做解释器**。触发信号写在这里备查：优先级编排变更、新事实维度（非文件名/phase/errorType）、规则间互斥需求。

### D4: DEFAULT_RULES 收窄为最小自愈集

内置默认值只保留能把 `RulesFileCorrupt` 自身错误事实判为重要并推送所需的最小规则（push.errors.errorTypes 含 `RulesFileCorrupt` 或 phases 含 `read_rules`，unmatched 兜底 silent）。业务默认值（added/removed 推、PageValidationError 等）只存在于出厂 `config/triage-rules.json`。这样 Claw 改 config 后不存在一份过期的代码内副本与之矛盾。

风险对应：首次运行且 config 缺失时，内置规则不再推送普通 diff——可接受，因为此时「规则文件损坏」告警本身会推送，群里能发现。

## Risks / Trade-offs

- [include 与 suppress 同时配错导致全量静默] → 校验不拦（合法配置），由 dry-run（`--once --dry-run`）与 skill 草案回显兜底；skill 回显时必须注明「过滤后将只推 N 类文件」。
- [fnmatch 模式写错（如少写 `*`）导致关注集为空] → 同上，草案回显 + 写后校验；校验器只保证类型合法，语义正确性靠人确认环节。
- [schema 扩充后旧代码读新配置] → 回滚代码不回滚 config 时，旧校验器遇 `filenameIncludePatterns` 判规则文件损坏、走自愈告警（不静默、不崩），可接受。

## Migration Plan

1. 改 `src/triage_rules.py` 与 `src/intranet_filename_monitor.py`，跑测试。
2. 出厂 `config/triage-rules.example.json`、`config/intranet-versions.example.json` 补新键注释样例；在用 config 文件不加键（保持现行为）。
3. 更新 `skills/ff-config-assistant/SKILL.md` 能力表与 `AGENTS.md` 规则一节。
4. 通知器/采集器热读生效，无需重启计划任务；回滚 = 还原 src 与 skill，config 未加新键则无兼容问题。
