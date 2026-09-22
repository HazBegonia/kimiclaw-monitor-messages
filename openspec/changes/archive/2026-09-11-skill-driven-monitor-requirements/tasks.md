# Tasks: skill-driven-monitor-requirements

## 1. 技术验证（先于一切改动）

- [x] 1.1 Spike：群内 @FF 发一条消息，确认 OpenClaw 唤起交互会话，并验证该会话内能读写项目文件（读写 `state/` 下临时文件测试）
- [x] 1.2 Spike：在 @FF 交互会话内调 `wecom-cli` 向「未命名企业」群发送一条测试消息并确认群内可见
- [x] 1.3 若 1.1/1.2 不成立：回到 design.md 记录降级方案（确认动作改为人手工编辑台账文件），并同步修订 tasks（实测通过：2026-09-11 15:42 @FF 会话成功唤起、写入项目 state/ 并在群内回复，无需降级；注意企微群消息会截断长文本，控制指令须保持极简）

## 2. SKILL.md 改造（skills/intranet-message-triage/SKILL.md）

- [x] 2.1 新增「采集需求」一节：人话说明 + 围栏 ```json 块（`monitor-requirements`），内容与现状等价（targets 含 `http://172.16.30.20:8011/`，versions 含 `103300110002`）
- [x] 2.2 新增「需求同步」流程小节：skillHash 比对 → 生成待确认需求 → 发群确认消息（含最终执行形态与操作指引）→ 仅已激活需求幂等生成 config（确定性照抄铁律写入本节）
- [x] 2.3 新增「控制指令」小节：交互会话只认 `开始` / `暂停` / `状态`，其余消息固定提示改 SKILL.md；含回执格式与多条需求时暂停须带 ID 的约定
- [x] 2.4 输入表补 `logs/intranet-focus/`（在架清单/原始材料的用途说明），打通断链
- [x] 2.5 明确职责边界：重要性判定规则改动不过确认闸；采集需求改动必须过闸

## 3. 需求台账

- [x] 3.1 创建 `state/requirements.json`，将当前现实需求以「已激活」状态直接登记（等价迁移，含 skillHash 初值）
- [x] 3.2 台账读写约定落进 SKILL.md：原子写（临时文件 + rename）、字段定义、状态机（待确认 → 已激活 ⇄ 已暂停，→ 已被取代为终态）

## 4. 脚本多目标改造（src/intranet_filename_monitor.py）

- [x] 4.1 新增 `config/monitors.json` 读取与校验（id/url/profile 必填，非法即 `read_config` 错误，不静默替代）
- [x] 4.2 `main()` 改为循环目标：每目标独立 state（`state/intranet-files-<id>.json`）、monitorId 含目标 ID；单目标失败记录后继续其余目标，退出码汇总
- [x] 4.3 生成初始 `config/monitors.json`（单目标等价现状）；`--versions-config` 参数保留
- [x] 4.4 无 monitors.json 时的兼容策略：报错退出（不用默认 URL 兜底），由台账同步负责生成配置

## 5. 测试

- [x] 5.1 `tests/test_intranet_filename_monitor.py` 补多目标用例：单目标等价现状、多目标状态隔离、单目标失败不影响其余目标
- [x] 5.2 补 monitors.json 损坏 → `read_config` 错误且不采集的用例
- [x] 5.3 全量回归：`python -m pytest tests/` 通过

## 6. 端到端演练与文档

- [x] 6.1 cron 两任务运行若干轮，确认 diff / focus / error 日志与改造前行为一致（回归基线）
- [x] 6.2 端到端演练：改 SKILL.md 需求段 → 收 FF 群确认消息 → @FF「开始」→ config 更新 → 脚本行为生效 → @FF「状态」核对台账
- [x] 6.3 演练「暂停」与「手工改 config 被覆盖」两个场景
- [x] 6.4 更新 `AGENTS.md`（需求入口、台账、控制指令、config 由 claw 生成的约定）
