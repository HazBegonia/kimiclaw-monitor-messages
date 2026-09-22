# chat-driven-skill-config-editing Specification (delta)

## REMOVED Requirements

### Requirement: 意图分类与只读查询

**Reason**: 自然语言意图分类依赖 @FF 的 LLM 交互会话，随 openclaw 整体退役冻结。
**Migration**: 只读查询过渡期通过本地文件（台账、游标、日志）人工查看；能力重建由后续 change 在有 LLM 预算时承载。

### Requirement: 草案生成与对照回显

**Reason**: 草案由 LLM 会话起草与回显，执行者退役。
**Migration**: 变更入口回到人工编辑文件；重要性规则的新入口是 `config/triage-rules.json`。

### Requirement: 单待写入草案

**Reason**: 草案机制整体冻结。
**Migration**: 无草案状态需要迁移；`state/chat-drafts.json` 保留为审计记录。

### Requirement: 写入与放弃指令

**Reason**: 指令依赖 @FF 的 LLM 会话。
**Migration**: 文件变更直接人工编辑，无需确认闸。

### Requirement: 歧义只追问不动笔

**Reason**: 歧义判定依赖 LLM 理解。
**Migration**: 无等价机制；人工编辑自担语义正确性，写坏由各文件的校验与自愈机制兜底（规则文件见 py-notifier-loop「规则文件自愈」）。

### Requirement: 写后校验与自动回滚

**Reason**: 校验执行者是 LLM 会话。
**Migration**: py 侧自愈机制承担等价保障：规则文件坏→沿用好规则+告警；config 坏→采集器 `read_config` 错误可见。

### Requirement: 分类生效路径

**Reason**: 生效路径的调度者（会话）退役。
**Migration**: 人工编辑即生效：规则下一轮热读，config 由采集器每轮热读，无需中间流程。

### Requirement: 运维 config 白名单

**Reason**: 对话修改渠道不存在，白名单失去意义。
**Migration**: 所有 config 过渡期均人工修改。

### Requirement: 草案留痕

**Reason**: 草案事件不再产生。
**Migration**: 留痕 JSONL 格式保留用于通知器自身的发送失败留痕（py-notifier-loop「发送成功才推进游标」）。
