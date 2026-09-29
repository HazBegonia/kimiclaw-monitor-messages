# Tasks

## 1. 修复假配置（triage_rules.py）

- [x] 1.1 在 `src/triage_rules.py` `evaluate_diff` 中应用 `suppress.filenamePatterns`：用 fnmatch 过滤 added/removed，剔除后为空则判不重要；推送正文只含剔除后文件名。验证：`tests/test_triage_rules.py` 新增用例（命中部分剔除、全部命中不推、空 patterns 不生效）通过
- [x] 1.2 `validate_rules` 增加未知字段显式拒绝（push/suppress/unmatched 三层枚举已知键，未知键抛 `RulesCorruptError`），并从 schema 移除 `semantic` 与 `consecutiveFetchFailures`。验证：含 `semantic` 的规则文件触发 `RulesCorruptError` 的测试通过
- [x] 1.3 从 `config/triage-rules.json` 删除 `semantic` 与 `push.errors.consecutiveFetchFailures` 字段。验证：`python -c "from pathlib import Path; from src.triage_rules import load_rules; load_rules(Path('config/triage-rules.json'))"` 通过；`pytest tests/test_triage_rules.py` 全绿
- [x] 1.4 更新 `src/triage_rules.py` 模块 docstring（移除「Reserved fields」段，改为描述 filenamePatterns 真实语义与未知字段拒绝）

## 2. 清场旧机制

- [x] 2.1 将 `skills/intranet-message-triage/SKILL.md` 移到 `wiki/`（保留作历史存档）。验证：`skills/` 下不再有该文件，`npx @fission-ai/openspec list` 与 git 状态符合预期
- [x] 2.2 归档 `state/requirements.json` 为 `state/backup-requirements-2026-09-24.json`（沿用既有 backup 命名惯例）。验证：原路径文件不存在，备份可读
- [x] 2.3 检查 `state/chat-drafts.json` 旧草案均为终态（已写入/已放弃/被取代），不是终态的置为被取代。验证：文件 JSON 可解析且无 `待写入` 状态草案

## 3. 新建 ff-config-assistant skill

- [x] 3.1 创建 `skills/ff-config-assistant/SKILL.md`：frontmatter（name/description/user-invocable）+ 职责边界 + 能力表（需求类型→目标文件→目标键→校验命令，含 design.md D4 四行）+ 草案协议（起草/回显/写入/放弃/顶掉/幂等）+ 白名单与拒绝话术 + 写后校验与回滚步骤 + 留痕格式（`logs/intranet-notify/` stage: config-change）+ 推送窗口丢消息对策。验证：`openspec validate ff-config-assistant --strict` 通过且 skill 内路径均为绝对路径
- [x] 3.2 在 skill 中写明 Claw 操作约束：写入前确认目标文件存在、用原子写（临时文件+replace）、草案 before 存完整原文、写后回读比对 after。验证：通读 skill 文本确认四约束齐备

## 4. 文档同步

- [x] 4.1 更新 `AGENTS.md` 当前架构节：对话变更走 ff-config-assistant（草案+确认闸），移除「config 均为人工直改」的过渡期表述；登记 `state/requirements.json` 废弃与旧 skill 存档位置。验证：AGENTS.md 中无与本 change 矛盾的描述
- [x] 4.2 更新 `docs/architecture.md` 与 `docs/operations.md` 中涉及 config 维护方式的段落。验证：两文档与 skill 能力表一致

## 5. 端到端验证

- [x] 5.1 实群走完整闭环：@FF 加测试版本 → 草案回显 → 写入 → `logs/intranet-focus/<测试版本>/` 出现快照目录 → 群内生效报告。验证：草案状态已写入 + 留痕行存在 + 快照目录出现
- [x] 5.2 演失败路径：起草一个校验必失败的变更（如非法 JSON 改后内容），写入后确认自动回滚且群内收到失败报告。验证：文件内容与写入前逐字节一致 + 草案状态已回滚
- [x] 5.3 演拒绝路径：@FF 发白名单外请求（如改轮询间隔），确认拒绝话术正确且无草案产生。验证：`state/chat-drafts.json` 无新增草案
- [x] 5.4 `pytest tests/` 全绿；`npx @fission-ai/openspec validate ff-config-assistant --strict` 通过
