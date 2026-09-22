# Design: skill-driven-monitor-requirements

## Context

现状（详见 proposal.md - Why）：

- `src/intranet_filename_monitor.py` 每轮扫描前已重读 `config/intranet-versions.json`（`main()` 内 `load_selected_versions`，出错记 `read_config` 错误日志）——"脚本读 config、出错走 flow2"的机制是现成的，本设计复用它。
- claw 侧已有两个定时任务（每分钟）：`intranet-file-monitor-once`（跑脚本 `--once`）与 `intranet-message-notify`（读 SKILL.md 做 triage + 推送）。需求同步步骤挂在 notify 任务上，不新增 cron。
- @FF 交互会话的行为链路（唤起会话、会话内读写项目文件、会话内调 wecom-cli 发群消息）**未实测**，是首个技术验证任务。
- 前提约束：目标群只有 FF 机器人 + 李非凡，交互会话不做鉴权。

## Goals / Non-Goals

**Goals:**

- 需求单源：SKILL.md「采集需求」段 → claw 理解 → 群确认 → 台账 → config → 脚本。
- 脚本哑化：多目标、版本快照、错误日志都是机制，不含业务语义。
- 未确认需求零影响：config 只由已激活需求生成。
- 失败可见：config 坏 → `read_config` 错误日志 → flow2 推送。

**Non-Goals:**

- 企业微信/钉钉消息源接入。
- 群聊自由文本反馈（"这类不重要"）——群聊只有三个控制指令。
- 重要性判定规则不过确认闸，不进台账（只影响 claw 判断，不碰脚本）。
- 页面 HTML 快照留档（讨论中提过，本期不做）。

## Decisions

### D1: 需求源放在 SKILL.md 内的人话+半结构化小节，而不是独立规则文件

「采集需求」段约定格式：一段人话说明 + 一个围栏 ```json 块（`monitor-requirements`，含 `versions` / `targets` 等机器字段）。claw 的理解动作以 json 块为准、人话为参照，生成的"最终执行形态"回显给人确认。

- 备选 A：独立 `config/triage-rules.json` 作源头——与"人只写 skill"的诉求不符，弃。
- 备选 B：纯人话、claw 自由理解——理解错了不报错（静默错误），弃。半结构化块把"理解"压缩为低风险的结构化提取，确认闸兜住剩余风险。
- 备选 C：脚本直接解析 SKILL.md 的围栏块——少一步同步，但把脚本和 markdown 格式耦合，人编辑弄坏格式脚本即停；且脚本还要逐目标读 monitors.json，两个源头不如一个生成产物清晰，弃。

### D2: 台账 state/requirements.json 作为两个 claw 上下文的唯一协作面

```
cron notify 任务（每分钟）          @FF 交互会话（事件驱动）
  skillHash 比对                    收到「开始」→ 激活待确认需求
  变化 → 生成待确认需求 → 发群确认    收到「暂停」→ 暂停已激活需求
  已激活需求 → 生成 config           收到「状态」→ 回台账摘要
         ↘ 都读写 state/requirements.json ↙
```

需求条目：`{id, content(最终执行形态 json), status, skillHash, proposedAt, statusChangedAt}`。状态机：`待确认 → 已激活 ⇄ 已暂停`，skillHash 变化时旧需求 → `已被取代`（终态，保留审计）。

- 竞态：两边写同一文件，但 cron 每分钟一次、交互极少，且都是"读-改-写"小文件，接受这个概率；写入沿用脚本侧已有的原子写（写临时文件再 rename）思路。
- 备选：用 git 历史代替台账——状态查询与回执都变复杂，弃。

### D3: config 生成是确定性照抄，不是创作

claw 同步 config 时，已激活需求的 `content` 块就是 config 内容的来源（逐字段合并：versions → intranet-versions.json，targets → monitors.json）。claw 不做任何超出需求内容的推断；内容一致则不重写（幂等）。这条写进 SKILL.md 作为铁律。

### D4: 多目标用 monitors.json + 每目标独立 state/monitorId

`config/monitors.json`：`[{"id": "intranet-root", "url": "...", "profile": {...}}]`。脚本 `main()` 循环目标，每目标独立 `--state`（如 `state/intranet-files-<id>.json`）、monitorId 带目标 ID；单目标失败 catch 后继续下一个目标，最后汇总退出码。默认配置与当前单 URL 行为完全等价（migration 见下）。

- 备选：一次跑一个目标、cron 注册 N 个任务——目标增减要动 cron 注册脚本，不如单任务循环自包含。
- 字段提取器类型维持现状（link_set / title / h1），新页面类型需要新提取器时再提新 change——YAGNI。

### D5: 交互会话的控制规范写在同一个 SKILL.md，但独立小节

不拆新 skill：@FF 会话由 OpenClaw 唤起时如何加载 skill 尚未实测，先在现有 skill 内加「控制指令」一节（cron 与交互都读同一个文件），待实测确认会话上下文形态后再决定是否拆分。这是设计里刻意推迟的点，不影响 spec。

### D6: 确认消息与回执的格式

确认消息包含：需求 ID、人话摘要、最终执行形态（json 内容）、操作指引（「确认请 @FF 回复：开始」）。回执包含操作后状态摘要。一轮最多一条确认消息（与现有推送聚合铁律一致），多条新需求合并为一条消息分节展示。

## Risks / Trade-offs

- [claw 理解半结构化块仍可能出错] → 确认闸：人确认的就是最终执行形态本身；不理解不确认就不落地。
- [claw 写出坏 config，脚本停摆] → `read_config` 错误已接 flow2，下轮即推送告警；且脚本失败保留最近成功 state，恢复后不丢 diff。
- [@FF 会话技术链路未验证] → tasks 第一步就是 spike 验证；若会话内不能写文件，则降级方案为「确认动作改为人手工改台账文件」，spec 不受影响（spec 只约束行为不约束实现）。
- [台账与 config 双写不一致] → config 完全由台账派生、幂等重写，台账是唯一事实；加「状态」指令让人随时可查。
- [focus 快照每版本每轮一份文件，磁盘增长] → 现状已如此且单页面量小；超出时另开 change 做轮转。
- [每轮 skillHash 比对需要 notify 任务读 SKILL.md] → 它本来每轮就读，零额外成本。

## Migration Plan

1. 技术验证（@FF 会话链路）通过后才开始改文件。
2.  SKILL.md 加「采集需求」段，内容与当前现实等价（目标 = `http://172.16.30.20:8011/`，版本 = `103300110002`），并加需求同步、控制指令小节；输入表补 `logs/intranet-focus/`。
3. 手工创建初始 `state/requirements.json`：将上述现实需求直接记为「已激活」（等价迁移，无需再走一遍确认）。
4. 脚本加 monitors.json 循环；生成 `config/monitors.json`（单目标，等价现状）；`--versions-config` 保留。
5. 回归：cron 两个任务跑若干轮，确认 diff/focus/error 日志与现状一致；然后做一次端到端演练——改 SKILL.md 需求段 → 收确认消息 → @FF 开始 → config 变化 → 脚本行为变化 → @FF 状态核对。
6. 回滚：SKILL.md 与 config 都在 git 内，revert 即可；台账删除即回到手工 config 时代（脚本行为不受台账存在与否影响，它只读 config）。

## Open Questions

- @FF 交互会话里 OpenClaw 给 agent 的上下文形态（能否读写项目文件、wecom-cli 是否可用）——spike 验证后回填到 SKILL.md 的控制指令小节。
- 「暂停」是否需要带需求 ID（多条已激活需求共存时）——实现时在控制指令小节约定：单条可省略，多条必须带 ID，否则回复列表请人选。
