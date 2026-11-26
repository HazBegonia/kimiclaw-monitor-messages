# Design

## Context

动机见 proposal.md。与实现相关的现状约束：

- Claw（OpenClaw gateway，`kimiclaw-openclaw-gateway.service`）通过 wecom 插件长连接收 @FF 群消息；`~/.openclaw/openclaw.json` 的 `skills.load.extraDirs` 已指向项目 `skills/`，@FF 会话会自动加载该目录下所有 skill。
- 已退役的 `skills/intranet-message-triage/SKILL.md` 仍在被加载，且 2026-09-23 已被实际触发走过两笔草案（见 `state/chat-drafts.json`）——半活的旧机制必须清场，否则新旧两套规则并存。
- config 全部热读：`triage-rules.json` 通知器每轮热读；`monitors.json` / `intranet-versions.json` 采集器每轮读取。写入即生效，无需重启——这是「确认后立即生效」的基础。
- 通知器借线推送的约 30 秒窗口内，@FF 群消息被服务器丢弃不补发（实测结论，见 `wiki/wecom-bot-connection-exclusivity.md`）。
- 现成的写后校验器：`src/triage_rules.py:load_rules`、`src/intranet_filename_monitor.py:load_selected_versions / load_monitors_config`，均为纯函数，可被 Claw 经 shell 单测式调用。
- `src/triage_rules.py:184` 已读取 `suppress.filenamePatterns` 但未使用；`validate_rules` 只校验其类型。

## Goals / Non-Goals

**Goals:**

- @FF 会话对「监控什么、推什么、推到哪」的变更请求形成闭环：理解 → 草案 → 确认 → 落盘 → 校验 → 回滚/生效 → 留痕。
- 消灭假配置：规则文件中每个字段要么有实现语义，要么不存在；未知字段显式判损坏。
- Claw 的修改边界由 skill 内的能力表机械判定，不依赖模型自觉。

**Non-Goals:**

- `monitors.json` 的 `profile.extension` 硬编码（陷阱 1）与文件内容变化监控——本 change 不动采集器解析逻辑。
- 轮询间隔、systemd unit、凭证——维持人工。
- `consecutiveFetchFailures` 的真实语义（上级未定义，连字段一起移除，将来定义后以新字段加回）。
- 需求台账派生层（`state/requirements.json` 状态机、「开始」激活闸）——不重建。

## Decisions

### D1: 直改 config，不重建台账派生层

config 就是唯一事实源（现状已是「人工直改即生效」），草案文件 `state/chat-drafts.json` 的 before/after 快照已满足审计与回滚需要。旧设计的「SKILL.md 需求块 → 派生 config」双层结构是当初 config 由 claw 生成时代的产物，现在只会制造两个可能漂移的事实源。

**备选**：忠实复刻旧台账机制（否决：多一层派生，多一个漂移点，工作量大且收益仅为形式审计）。

### D2: 新 skill 取代旧 skill，而不是修补旧文件

新建 `skills/ff-config-assistant/SKILL.md`，把 `skills/intranet-message-triage/SKILL.md` 移到 `wiki/` 存档（其内容大量描述已退役的 triage 链路与 Windows 计划任务，修补比重写贵）。`extraDirs` 配置不动，移出即卸载。新 skill 只含：职责边界、能力表、草案协议、白名单、写后校验、留痕格式、推送窗口丢消息对策。

### D3: 能力表驱动边界，逐字指令做确认闸

skill 内置一张「需求类型 → 目标文件 → 目标键 → 校验命令」表；Claw 收到请求先对表：表内 → 起草；表外 → 拒绝并说明人工路径。确认只认逐字「写入」「放弃」（企微群消息会截断长文本，指令必须极简；且自然语言确认如「好的」歧义太大）。

**备选**：自然语言确认 + 模型判断（否决：企微场景下「好的」「嗯」是否为确认无法可靠区分，误落盘代价比多打两个字大）。

### D4: 写后校验复用现成 py 校验器，失败用草案 before 快照回滚

每个白名单目标绑定一条校验命令：

| 目标文件 | 校验命令 |
|---|---|
| `config/intranet-versions.json` | `python -c "from pathlib import Path; from src.intranet_filename_monitor import load_selected_versions; load_selected_versions(Path('config/intranet-versions.json'))"` |
| `config/monitors.json` | `python -c "from pathlib import Path; from src.intranet_filename_monitor import load_monitors_config; load_monitors_config(Path('config/monitors.json'))"` |
| `config/triage-rules.json` | `python -c "from pathlib import Path; from src.triage_rules import load_rules; load_rules(Path('config/triage-rules.json'))"` |
| `config/notifier.json` | `python -c "import json; d=json.load(open('config/notifier.json')); assert d['chatid']"` |

草案的 `before` 字段存完整原文（非 diff），回滚 = 原子写回原文。校验通过后回读文件与草案 `after` 比对，确认落盘内容即草案内容（防夹带）。

### D5: filenamePatterns 用语义最简的 fnmatch 通配，判定前剔除

`src/triage_rules.py:evaluate_diff` 中，对 added/removed 两列表先按 `suppress.filenamePatterns` 的 fnmatch 模式过滤，过滤后再走原有判定；正文只出现剔除后的文件名。选 fnmatch 而非正则：上级与 Claw 都只需 `*tmp*` 这种级别，正则写错就是新的假配置温床。留痕/群回复中注明被剔除数量（如「已按规则忽略 2 个匹配文件」），避免「文件来了却没推」被当成漏报。

### D6: 未知字段显式拒绝，自愈链路兜底

`validate_rules` 对 `push/suppress/unmatched` 三层做已知键枚举，遇未知键抛 `RulesCorruptError`。这把「将来有人/Claw 手写了一个没实现的字段」从静默失效变成群内告警。迁移代价：现网 config 含 `semantic` 与 `consecutiveFetchFailures`，必须与本 change 的 config 清理同批发布，否则上线即报损坏告警。

### D7: 草案状态机与文件格式

`state/chat-drafts.json` 沿用现有结构（`drafts` 数组），状态机简化为：`待写入 → 已写入 / 已放弃 / 已回滚`，外加新草案顶掉旧草案时的 `被取代`。写文件用采集器同款原子写（临时文件 + replace）。留痕进 `logs/intranet-notify/` 当日 JSONL，stage 固定 `config-change`，与通知器既有留痕同目录不同 stage，互不干扰。

## Risks / Trade-offs

- [确认指令在推送窗口被吞，流程卡住] → 草案持久化 + 每次收到消息先提示待确认草案，上级重发即可；窗口仅约 30 秒且仅在推送时发生。
- [Claw 幻觉出能力表外的「可改项」] → 能力表内每条绑定具体校验命令；写后校验 + 回读比对 after 兜底；白名单外明确拒绝话术。
- [未知字段拒绝误伤人工新增字段] → 这正是设计意图（新增字段必须连实现一起上）；告警文案说明「字段未实现或被拼错」。
- [Claw 会话上下文里没有项目根路径概念，写错位置] → skill 中所有路径写绝对路径 `/home/u504/.openclaw/workspace/kimiclaw-monitor-messages/...`，并要求写入前 `ls` 目标文件存在。
- [filenamePatterns 剔除导致「文件来了没推」被误解为漏报] → 群回复注明剔除数量（D5）。
- [多人群聊里他人误发「写入」] → 现网群为测试企业全员群，成员即上级本人与小范围测试者；正式环境如出现此问题，再考虑发起人匹配（届时会改确认闸语义，属后续 change）。

## Migration Plan

1. 改 `src/triage_rules.py`（filenamePatterns 生效 + 未知字段拒绝 + 移除两个占位字段的 schema）与 `config/triage-rules.json`（删占位字段），跑 `tests/test_triage_rules.py`。
2. 移 `skills/intranet-message-triage/SKILL.md` → `wiki/`，新建 `skills/ff-config-assistant/SKILL.md`。
3. 归档 `state/requirements.json`（移入 `state/backup-*` 命名，同既有回滚备份惯例）。
4. 验证：在群里走一笔完整闭环（加一个测试版本 → 写入 → 观察 `logs/intranet-focus/` 出现对应目录 → 放弃/回滚各演一遍）。
5. 回滚：旧 skill 从 `wiki/` 移回 `skills/`、config 从 git 历史恢复、triage_rules.py 回滚——分钟级。

## Open Questions

- `consecutiveFetchFailures` 与 `semantic` 的真实语义等上级定义后以新 change 加回（字段名、行为都届时再定）。
