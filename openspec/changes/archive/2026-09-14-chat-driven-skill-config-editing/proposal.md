# Proposal: chat-driven-skill-config-editing

## Why

当前需求变更的唯一入口是人手动编辑 SKILL.md：人话与 JSON 块可能写不一致、JSON 可能写错、模糊意图（"删掉旧版本"）没有任何机制能反问澄清。通过与 FF 机器人对话来提出变更，由模型把模糊人话翻译成精确的结构化改动并回显改前/改后对照，人确认后才落盘——用"模型起草 + 人确认"换取变更的精确性。这是对现有「确认闸」的前移增强，不是另开生效通道。

## What Changes

- 新增**对话草案协议**：群内 @FF 的自然语言变更请求被解析为草案（改前→改后 diff + 最终执行形态），存入 `state/chat-drafts.json`，回复「写入」才落盘文件，「放弃」作废；同时只允许一个待写入草案，新草案取代旧草案。
- 草案覆盖三类对象（生效深度不同）：
  - **采集需求块**（targets / versions / scanInterval）：写入 SKILL.md 后走现有需求同步流程，仍需「开始」激活才派生 config 与计划任务——三重关卡。
  - **重要性判定规则**（自由文本节）：写入即生效（triage 每轮重读 SKILL.md），粒度为条目级增删改，不做整节自由重写。
  - **运维 config 白名单**（如 wecom-aibot.json 群名、triage-message.txt）：写入即生效，写后立刻验证（如 sessions list 核对新群名），失败自动回滚。
- **写后校验 + 自动回滚**：任何草案落盘后立刻重新校验（JSON 可解析、需求块结构完整、config 可加载），失败即回滚并群内报告。
- **BREAKING（行为规范层面）**：`@FF` 会话不再对自由文本一律回绝——非指令消息进入意图分类（需求修改 / 规则修改 / 配置修改 / 只读查询 / 无法解析），无法解析时才回固定帮助文案。指令集新增「写入」「放弃」。
- 解析纪律：拿不准只追问不动笔；草案确认消息必须带改前→改后对照。
- 只读查询（"现在监控哪些版本"等）零门槛支持，不产生草案、不改状态。

## Capabilities

### New Capabilities

- `chat-driven-skill-config-editing`: 群内 @FF 自然语言变更请求的解析、草案生命周期（生成/写入/放弃/取代）、写后校验与自动回滚、运维 config 白名单、只读查询与留痕。

### Modified Capabilities

- `wecom-bot-control-commands`: 「受限指令集」需求变更——指令集扩展为 开始/暂停/状态/写入/放弃；自由文本不再一律回绝，而是进入草案解析或只读查询。
- `skill-driven-requirement-lifecycle`: 「SKILL.md 采集需求段为唯一需求来源」需求变更——唯一来源原则不变，但增加 claw 代笔路径：群聊草案经「写入」确认后由 claw 把变更写入 SKILL.md，再走既有 hash 检测与确认闸。

## Impact

- **代码**：无 Python/脚本改动；全部变化集中在 `skills/intranet-message-triage/SKILL.md`（职责边界、控制指令节改写，新增「对话草案」节）与新建 `state/chat-drafts.json`（运行时生成）。
- **文档**：AGENTS.md 发送渠道现状、wiki/log.md 同步。
- **行为规范**：@FF 交互会话的职责从纯控制面扩为控制面 + 变更起草；「群聊只言片语一律不生效」原则由「草案确认后才落盘」替代。
- **依赖**：无新增依赖；沿用 wecom-cli、现有台账与原子写约定。
