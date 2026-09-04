# Spec: openclaw-runtime

## Purpose

保障本机 OpenClaw 运行时处于可用、可复现状态：独立 Node/npm 环境、全局可调用的 openclaw CLI、复用既有 `~/.openclaw` 配置、接入 Kimi For Coding Key 作为主模型，并通过冒烟测试验证链路，为最小尝试（内网监视 → 过滤 → .log）提供 agent 执行底座。

## ADDED Requirements

### Requirement: 独立 Node.js 与 npm 全局环境

系统 SHALL 使用独立于 Kimi 桌面版运行时的 Node.js LTS，并将 npm 全局安装目录指向独立路径，且该路径在用户 PATH 中。

#### Scenario: 新 shell 中直接可用

- **WHEN** 打开一个新的 Git Bash 或 PowerShell 窗口
- **THEN** `node --version`、`npm --version`、`openclaw --version` 均无需完整路径即可执行成功

#### Scenario: npm 全局目录独立

- **WHEN** 执行 `npm config get prefix`
- **THEN** 返回值不是 Kimi 桌面版运行时目录（`...kimi-desktop\daimon-share...`），而是独立目录（如 `C:\Tools\npm-global`）

### Requirement: openclaw CLI 恢复并复用既有配置

系统 SHALL 全局安装与既有配置兼容的 openclaw 版本（2026.7.1），安装后 `~/.openclaw` 下的既有配置（渠道、hooks、插件）保持可用。

#### Scenario: 配置无损复用

- **WHEN** openclaw 重装完成后启动 gateway
- **THEN** gateway 能正常启动，且既有 `openclaw-weixin` 插件与 `oc/openclaw-hooks` 下的 hook 配置不报错

#### Scenario: 版本对齐

- **WHEN** 执行 `openclaw --version`
- **THEN** 输出版本与 `~/.openclaw/openclaw.json` 中 `meta.lastTouchedVersion` 的主版本一致（2026.7.x）

### Requirement: Kimi For Coding provider 接入

系统 SHALL 在 openclaw 配置中包含 Kimi For Coding provider（`https://api.kimi.com/coding/v1`，OpenAI 兼容），并将 agent 主模型切换到该 provider；原有中转站 provider 保留为 fallback。

#### Scenario: 主模型切换

- **WHEN** 查看 agent 默认模型配置
- **THEN** primary 模型指向 Kimi provider 的模型（如 `kimi-coding/k3-256k`），且 zhehentiaohe provider 配置仍然存在

#### Scenario: 密钥不落明文文档

- **WHEN** 检查工作区内所有文档、报告与 openspec 工件
- **THEN** 不出现完整 API Key（只允许 `sk-kimi-xxx****` 形式的掩码）

### Requirement: 冒烟测试通过

系统 SHALL 能通过 openclaw 使用 Kimi key 完成一次真实模型对话。

#### Scenario: TUI 对话验证

- **WHEN** 在 openclaw 中发送一条测试消息（如"回复 OK"）
- **THEN** 收到 Kimi 模型的正常响应，且日志显示请求发往 `api.kimi.com`

#### Scenario: 失败可回退

- **WHEN** Kimi provider 不可用（401/429/网络失败）
- **THEN** 可通过配置切换回 zhehentiaohe fallback，且配置文件存在最近备份

### Requirement: 可选 Kimi 插件关联

系统 MAY 通过 kimi.com/bot 的"关联已有 OpenClaw"流程将本机实例接入 Kimi 网页端；该流程失败或被会员门槛拦截时不得影响上述必备能力。

#### Scenario: 关联尝试有结论

- **WHEN** 使用无会员 Kimi 账号执行关联流程
- **THEN** 结果为"关联成功"或"明确记录失败原因（如会员门槛）"之一，且失败时 openclaw 本体功能不受影响
