# Spec Delta

## MODIFIED Requirements

### Requirement: 白名单边界

对话修改 MUST 仅限白名单内目标：`config/intranet-versions.json`（关注版本 CRUD，含每选择项的 `id`、`match` 与可选 `mode`）、`config/monitors.json`（监控目标 CRUD）、`config/triage-rules.json`（推送规则条目级，含 `push.diff.filenameIncludePatterns` 关注模式）、`config/notifier.json`（chatid）。白名单外的一切目标（源代码、密钥、systemd unit、轮询间隔、skill 文件自身）MUST 拒绝并说明原因与人工处理路径。白名单本身只能由人直接编辑 skill 文件修改，MUST NOT 走对话。

#### Scenario: 白名单内修改被受理

- **WHEN** 收到「@FF 删除字段 103300110002」
- **THEN** 正常起草 `config/intranet-versions.json` 草案

#### Scenario: 关注模式修改被受理

- **WHEN** 收到「@FF 以后新增文件只推文件名带 103300110002 的」
- **THEN** 正常起草 `config/triage-rules.json` 草案，条目级修改 `push.diff.filenameIncludePatterns`

#### Scenario: 匹配模式修改被受理

- **WHEN** 收到「@FF 把字段 103300110002 的匹配改成通配符 report-*-103300110002.csv」
- **THEN** 正常起草 `config/intranet-versions.json` 草案，将该选择项的 `mode` 置为 `fnmatch`

#### Scenario: 白名单外修改被拒绝

- **WHEN** 收到「@FF 把轮询间隔改成 2 秒」
- **THEN** 回复拒绝，说明轮询间隔是 systemd unit 启动参数，需人工修改并重启服务，不产生草案
