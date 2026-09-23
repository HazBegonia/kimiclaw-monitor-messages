# Proposal: setup-openclaw-kimi-key

## Why

最小尝试阶段（内网 web 监视 → 重要性过滤 → 本地 .log）需要一个可用的 OpenClaw 运行时，但本机现状是：openclaw 曾安装并跑通过 gateway（2026-08-28，配置在 `~/.openclaw/` 完好），然而 CLI 本体已丢失（npm prefix 指向 Kimi 桌面版共享运行时目录，疑似被升级清掉）；且现有 provider 是第三方中转站 `api.zhehentiaohe.cn/gpt-5.6-luna`，并非已确认的 Kimi For Coding Key（实测 `https://api.kimi.com/coding/v1` 可用，模型 k3 / k3-256k / kimi-for-coding）。需要把 openclaw 恢复到稳定、可复现的安装形态，并接入真实 Kimi key，为后续 flow1/flow2 落地打底。

## What Changes

- 安装独立 Node.js LTS（不再借用 Kimi 桌面版内嵌 node），并将 npm 全局 prefix 迁到独立目录（如 `C:\Tools\npm-global`），加入用户 PATH
- 全局安装 `openclaw@2026.7.1`（与 `~/.openclaw/openclaw.json` 的 `lastTouchedVersion` 对齐），复用现有配置
- 在 `~/.openclaw/openclaw.json` 新增 Kimi For Coding provider：`baseUrl=https://api.kimi.com/coding/v1`、`api=openai-completions`、模型 `k3-256k`（主用）/ `kimi-for-coding`，并将 agent 主模型切换至该 provider；保留 zhehentiaohe 中转站配置作为 fallback（不删除）
- 冒烟测试：通过 openclaw CLI/TUI 发送一条测试消息，验证 Kimi key 返回正常
- 可选：用无会员 Kimi 账号在 kimi.com/bot 走"关联已有 OpenClaw"流程安装 Kimi 插件（是否需要会员官方未写明，实测确认；不成功不阻塞主目标）

## Capabilities

### New Capabilities

- `openclaw-runtime`: 本机 OpenClaw 运行时的可用性保障——独立 Node/npm 环境、openclaw CLI 可全局调用、`~/.openclaw` 配置复用与备份、Kimi For Coding provider 接入与主模型切换、冒烟验证、可选 Kimi 插件关联

### Modified Capabilities

（无）

## Impact

- **系统级**：新增 Node.js LTS 安装；修改用户 PATH 与 npm prefix（全局配置，不受"文件必须放工作区"约束，属 AGENTS.md 允许的全局配置例外）
- **配置**：`~/.openclaw/openclaw.json`（修改前必须备份，已有 `last-good` 机制）
- **密钥**：Kimi For Coding Key 只写入 `openclaw.json`，不进入任何报告、代码或 git 提交
- **不动**：`Desktop\program\oc\openclaw-hooks`（现有 hooks）、openclaw-weixin 插件配置保持原样
- **风险**：npm 全局目录迁移后，旧的（已丢失的）全局包不会自动迁移——目前全局目录为空，无实际影响
