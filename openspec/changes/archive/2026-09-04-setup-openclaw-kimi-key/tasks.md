# Tasks: setup-openclaw-kimi-key

## 1. 独立 Node.js 与 npm 环境

- [x] 1.1 安装 Node.js LTS（优先 `winget install OpenJS.NodeJS.LTS`；失败则下载便携 zip 解压到 `C:\Tools\node`）。验证：新 shell 中 `node --version` 输出版本号
- [x] 1.2 设置独立 npm 全局目录：`npm config set prefix C:\Tools\npm-global`。验证：`npm config get prefix` 返回 `C:\Tools\npm-global`
- [x] 1.3 将 Node 目录与 `C:\Tools\npm-global` 写入用户 PATH。验证：**新开的** Git Bash 和 PowerShell 窗口中 `node -v`、`npm -v` 均可直接执行

## 2. 恢复 openclaw CLI

- [x] 2.1 备份现有配置：`cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.setup-kimi`。验证：备份文件存在
- [x] 2.2 全局安装 openclaw：`npm i -g openclaw@2026.7.1`。验证：新 shell 中 `openclaw --version` 输出 2026.7.x
- [x] 2.3 启动 gateway 验证既有配置复用：`openclaw gateway start` 后观察日志。验证：gateway ready，无配置解析错误；随后 `openclaw gateway stop`（weixin 插件如报配对类警告可记录暂不处理）

## 3. 接入 Kimi For Coding Key

- [x] 3.1 编辑 `~/.openclaw/openclaw.json`：新增 `models.providers.kimi-coding`（`baseUrl=https://api.kimi.com/coding/v1`，`api=openai-completions`，`apiKey` 填入 Kimi For Coding Key，models 含 `k3-256k` 与 `kimi-for-coding`，contextWindow 262144）。验证：`openclaw` 启动无 JSON 语法/校验错误
- [x] 3.2 将 `agents.defaults.model.primary` 切换为 `kimi-coding/k3-256k`，保留 zhehentiaohe provider 不动。验证：gateway 启动日志中 `agent model` 显示 `kimi-coding/k3-256k`
- [x] 3.3 冒烟测试：通过 openclaw TUI/CLI 发送测试消息。验证：收到正常回复，且日志/网络记录显示请求发往 `api.kimi.com`；失败时按 design.md 风险表依次换 `kimi-for-coding`、调整 reasoning 配置后重试
- [x] 3.4 确认工作区工件无泄密：全文检索工作区（含 openspec/、docs/）不出现完整 Key。验证：`grep -r "sk-kimi-Up" openspec/ docs/` 无命中

## 4. 可选：Kimi 插件关联

- [x] 4.1 用无会员 Kimi 账号登录 kimi.com/bot，尝试"关联已有 OpenClaw"流程。结果：插件安装成功且本地 bridge 已连接，但网页端显示“连接失败，请重试”；页面要求 OpenClaw V2026.4.14 及以下，本机为 2026.7.1-2，详见 `docs/openclaw环境实施记录.md`
- [x] 4.2 若关联成功，安装 Kimi 插件并在 kimi.com 网页端向 openclaw 发一条消息。结果：因 4.1 网页端关联失败，本条件任务不适用；本地插件已安装并启用

## 5. 收尾

- [x] 5.1 更新 `docs/` 或实施记录：写明最终 provider 配置形态（掩码）、可用模型清单、fallback 切换方法。验证：文档存在且不含完整 Key
- [x] 5.2 全量回归：重启 gateway，确认 Kimi 主模型可用、配置备份齐全。验证：`openclaw gateway start` 日志 clean，`agent model` 为 `kimi-coding/k3-256k`
