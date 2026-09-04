# OpenClaw + Kimi Key 环境实施记录

> 日期：2026-09-04
> 对应 change：`openspec/changes/setup-openclaw-kimi-key`
> 状态：主目标已完成；Kimi 插件已安装，但网页端关联验证失败（不影响本地 OpenClaw）

## 最终环境形态

| 组件 | 位置 / 值 | 说明 |
|---|---|---|
| Node.js | `C:\Users\ELadmin\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64` | v24.16.0 LTS，winget 安装，用户 PATH 首位 |
| npm 全局目录 | `C:\Tools\npm-global` | 用户环境变量 `NPM_CONFIG_PREFIX` + `~/.npmrc` 双重指定 |
| openclaw CLI | `C:\Tools\npm-global\openclaw.cmd` | 版本 2026.7.1，与 `~/.openclaw/openclaw.json` 的 `lastTouchedVersion` 对齐 |
| openclaw 配置 | `C:\Users\ELadmin\.openclaw\openclaw.json` | 备份：`openclaw.json.bak.setup-kimi` |

## provider 配置（密钥已掩码）

- **主模型**：`kimi-coding/k3-256k`
  - `baseUrl`: `https://api.kimi.com/coding/v1`（Kimi For Coding 订阅端点，OpenAI 兼容）
  - `apiKey`: `sk-kimi-Up****`（仅存于 openclaw.json）
  - 备选模型同 provider：`kimi-for-coding`（K2.7 Coding）
- **fallback**：`custom-api-zhehentiaohe-cn/gpt-5.6-luna`（原样保留；切回方法：把 `agents.defaults.model.primary` 改回 `custom-api-zhehentiaohe-cn/gpt-5.6-luna` 即可）

## 验证结果

- `openclaw --version` → `OpenClaw 2026.7.1 (2d2ddc4)` ✅
- `openclaw gateway run` → ready，既有 `openclaw-weixin` 渠道从上次 sync buf 恢复、4 个 internal hooks 加载成功、9 个插件在线 ✅
- 冒烟：`openclaw agent --local --agent main --session-id smoke-test-01 -m "只回复两个字：你好"` → provider `kimi-coding`、模型 `k3-256k`、POST `api.kimi.com/coding/v1/chat/completions` 返回 200，回复"你好" ✅
- 工作区泄密检查：无完整 Key 命中 ✅

## Kimi 网页端关联验证（可选任务）

- 已登录 `kimi.com/bot`，打开“关联已有 OpenClaw”。
- 按页面提供的命令完成插件安装：`kimi-claw` 插件安装成功并启用，gateway 自动重启。
- 本地 gateway 日志确认 `kimi-bridge` 已启动并连接 `wss://www.kimi.com/api-claw/bots/agent-ws`，订阅连接成功。
- 点击“我已运行”后，网页端最终显示“连接失败，请重试”。本次关联结果记为失败；未继续重复生成 token 或重装。
- 页面提示关联命令适用于 OpenClaw V2026.4.14 及以下版本；本机为 2026.7.1-2，版本不匹配是本次失败的主要疑因（未为可选功能降级本机运行时）。
- 因关联未成功，网页端发消息验证（任务 4.2）不适用；本地 OpenClaw + Kimi Key 主链路保持可用。

## 注意事项

1. **Kimi 桌面版环境变量陷阱**：Kimi 桌面版运行时会给其子进程注入 `OPENCLAW_HOME` / `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH`（指向 openclaw-shim 空配置）。从 Kimi 会话里跑 openclaw 命令必须先 `unset` 这四个变量（含 `CLAWDBOT_STATE_DIR`），否则读到的是 shim 空配置。在普通终端（资源管理器新开的窗口）无此问题。
2. **Kimi For Coding 是订阅额度**（时间窗口限频，非按 token 计费）；监视类任务建议继续用 `k3-256k`，避免 1M 上下文的 `k3`。
3. doctor 自动安装了官方 `kimi` / `moonshot` provider 插件（`@openclaw/kimi-provider`、`@openclaw/moonshot-provider`），当前未在 `plugins.allow` 白名单中，按需再加。
4. gateway 每次启动生成临时 auth token；如需固定，执行 `openclaw config set gateway.auth.mode token` + `gateway.auth.token <token>`。
5. Key 曾出现在聊天记录中，建议方便时在 Kimi 会员页轮换一次。

## 待办（可选）

- 如需再次尝试，可在 kimi.com/bot 点击“重试”获取新 token，并重新执行官方安装命令；当前失败不影响本地运行。
