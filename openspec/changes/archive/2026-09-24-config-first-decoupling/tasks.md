# Tasks

## 1. triage-rules 增加 include 维度

- [x] 1.1 `src/triage_rules.py`：`_ALLOWED_KEYS` 的 `("push", "diff")` 集合加入 `filenameIncludePatterns`；`validate_rules` 对该键做可选字符串数组校验（缺省/空 = 不过滤，非字符串数组判损坏）。验证：`python -c "from pathlib import Path; from src.triage_rules import load_rules; load_rules(Path('config/triage-rules.json'))"` 对现有 config 通过
- [x] 1.2 `src/triage_rules.py`：`RulesEngine` 增加 include 过滤——`evaluate_diff` 与 `filter_diff_fact` 在 suppress 剔除之后执行关注过滤（`push.diff.filenameIncludePatterns` 非空时，未命中任一 fnmatch 模式的文件名从判定与渲染中剔除，剔除数量并入 `suppressedFilenames` 口径）。验证：新测试用例覆盖 spec「关注过滤只推命中项 / 全空不推 / 缺省保持现行为」三个场景
- [x] 1.3 `tests/test_triage_rules.py`：补齐 include 维度的校验与判定用例（含与 suppress 同时存在时的顺序：先 suppress 后 include）。验证：`python -m pytest tests/test_triage_rules.py -q` 全绿
- [x] 1.4 `config/triage-rules.example.json` 补 `filenameIncludePatterns` 样例（默认空列表）；在用 `config/triage-rules.json` 不加键。验证：example 文件通过 `load_rules` 校验

## 2. 版本匹配增加 mode

- [x] 2.1 `src/intranet_filename_monitor.py`：`load_selected_versions` 认可选 `mode` 键，校验取值 ∈ {substring, fnmatch}、缺省补 `substring`，非法值抛错（走 read_config 错误路径）。验证：非法 mode 的临时配置触发 ValueError
- [x] 2.2 `src/intranet_filename_monitor.py`：`filter_version_files` 按 `mode` 分发（substring = 现行为 `in`，fnmatch = `fnmatch.fnmatch` 全名匹配）。验证：新测试用例覆盖 spec「fnmatch mode selection / Invalid mode rejected」场景
- [x] 2.3 `tests/test_intranet_filename_monitor.py`：补齐 mode 校验与匹配用例（含缺省兼容）。验证：`python -m pytest tests/test_intranet_filename_monitor.py -q` 全绿
- [x] 2.4 `config/intranet-versions.example.json` 补 `mode` 样例与说明；在用 `config/intranet-versions.json` 不加键。验证：example 文件通过 `load_selected_versions` 校验

## 3. DEFAULT_RULES 收窄

- [x] 3.1 `src/triage_rules.py`：`DEFAULT_RULES` 收窄为仅保证 `RulesFileCorrupt` 自身错误事实判为重要的最小集（errorTypes 含 `RulesFileCorrupt`、unmatched 兜底 silent、无业务默认值）。验证：新用例「无 last-good 且规则文件缺失时，RulesFileCorrupt 事实判重要、普通 diff 判不重要」通过
- [x] 3.2 同步模块 docstring 中关于默认规则的描述，使其与收窄后行为一致。验证：通读 docstring 无过期表述

## 4. skill 与文档同步

- [x] 4.1 `skills/ff-config-assistant/SKILL.md` 能力表：`triage-rules.json` 行补 `filenameIncludePatterns`（关注模式），`intranet-versions.json` 行补可选 `mode`（substring/fnmatch）；规则细节节补一句 include 与 suppress 的顺序与口径。验证：能力表条目与 `validate_rules`/`load_selected_versions` 实际接受的键一一对应
- [x] 4.2 `AGENTS.md`「规则」一节补 include 维度与 mode 字段的现行事实。验证：通读无与代码行为矛盾的表述

## 5. 集成验证

- [x] 5.1 全量测试 `python -m pytest tests/ -q` 全绿（109 passed）
- [x] 5.2 `python -m src.intranet_notifier --once --dry-run` 对在用配置正常跑通（不发送、不推进游标，退出码 0）
