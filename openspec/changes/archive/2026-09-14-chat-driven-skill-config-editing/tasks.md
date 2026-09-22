# Tasks: chat-driven-skill-config-editing

## 1. SKILL.md 改写（skills/intranet-message-triage/SKILL.md）

- [x] 1.1 改写「职责边界」节：废除"群聊只言片语一律不生效"，说明群聊可发起变更草案但须经「写入」落盘；frontmatter description 同步更新
- [x] 1.2 新增「对话草案」节：`state/chat-drafts.json` 结构（原话/解析/目标类型/改前改后/状态）、单待写入草案与新草案取代规则、意图分类（需求块/规则/config/只读查询/无法解析）、歧义只追问不动笔
- [x] 1.3 「控制指令」节扩展为五个指令（开始/暂停/状态/写入/放弃），写入/放弃语义与无草案时的行为
- [x] 1.4 写入后的分类生效路径：需求块→需求同步+「开始」激活；规则→写入即生效（条目级增删改，禁整节重写）；config→写入即生效+写后验证
- [x] 1.5 「写后校验与自动回滚」规程：SKILL.md 块可提取可解析、config JSON 可加载、群名 sessions list 验证；失败用草案内改前内容回滚并群内报告
- [x] 1.6 运维 config 白名单写入 SKILL.md（初始：wecom-aibot.json 群名字段、triage-message.txt 全文；白名单本身只能手工改）
- [x] 1.7 草案留痕格式写入 SKILL.md（logs/intranet-notify/ JSONL，stage: chat-draft，含原话前 80 字符摘要）

## 2. 演练验证（需 gateway 在线 + 群内可 @FF）

- [x] 2.1 需求块草案全链路：@FF「关注版本加一个 X」→ 草案对照回显 → 写入 → 收到需求确认消息 → 开始 → config/intranet-versions.json 含新版本 → 台账/留痕正确 → 演练后恢复
- [x] 2.2 规则条目草案：@FF 新增一条不重要规则 → 写入 → SKILL.md 条目正确、块结构完好 → 下一轮 triage 按新规则执行
- [x] 2.3 config 草案回滚路径：@FF 改群名为不存在的群 → 写入 → sessions list 验证失败 → 自动回滚、群内收到失败报告、推送通道仍可用
- [x] 2.4 边界行为：歧义请求被追问不动笔；「放弃」作废草案；新草案取代旧草案；只读查询不改状态；无法解析回帮助文案
- [x] 2.5 检查 logs/intranet-notify/ 留痕覆盖草案全事件，state/chat-drafts.json 状态机正确

## 3. 文档同步

- [x] 3.1 AGENTS.md「发送渠道现状」补充对话草案入口（群聊可发起变更，写入+开始双闸）
- [x] 3.2 wiki/log.md 记录本次变更要点与演练结果
