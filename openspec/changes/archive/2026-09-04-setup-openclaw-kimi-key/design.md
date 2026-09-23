# Design: setup-openclaw-kimi-key

## Context

本机现状（2026-09-03 实测）：

- `~/.openclaw/` 配置完整（`openclaw.json` + 多个备份 + sqlite），2026-08-28 曾成功运行 gateway，插件 `openclaw-weixin`、hooks 目录 `Desktop\program\oc\openclaw-hooks` 均在线
- openclaw CLI 本体已丢失：npm prefix 指向 `C:\Users\ELadmin\AppData\Roaming\kimi-desktop\daimon-share\daimon\npm-global`（该目录已空/不存在），推断 openclaw 当初装在这里、被 Kimi 桌面版升级清掉
- 本机无独立 Node.js，仅有 Kimi 桌面版内嵌 node/npm（`command-process-owner\bin\`）
- 当前 provider：`custom-api-zhehentiaohe-cn`（`api.zhehentiaohe.cn/v1`，`gpt-5.6-luna`），非 Kimi
- 已有 Kimi For Coding Key（`sk-kimi-` 前缀），实测 `https://api.kimi.com/coding/v1/models` 返回 200，可用模型：`k3`（1M ctx）、`k3-256k`、`kimi-for-coding`、`kimi-for-coding-highspeed`
- 用户持有无会员 Kimi 账号；已授权安装任何软件

## Goals / Non-Goals

**Goals:**

- openclaw CLI 恢复到"任意新 shell 可直接调用"的稳定形态，不再依赖 Kimi 桌面版运行时
- agent 主模型走真实 Kimi key（Kimi For Coding 端点），冒烟通过
- 全程不破坏既有 weixin 渠道与 hooks 配置；改动前必有备份
- 可选完成 kimi.com/bot 关联已有实例（Kimi 插件）

**Non-Goals:**

- 不实现 flow1/flow2（内网监视、.log 生成、重要性过滤）——那是后续 change 的范围
- 不配置企业微信/钉钉渠道
- 不卸载或改动 Kimi 桌面版本体
- 不迁移/清理 `~/.openclaw` 历史数据

## Decisions

### D1: 独立 Node.js LTS + 独立 npm prefix

- **决定**：安装 Node.js LTS（winget `OpenJS.NodeJS.LTS` 或官网 msi）到默认位置；`npm config set prefix C:\Tools\npm-global`；将 `C:\Tools\npm-global` 加入用户 PATH
- **理由**：上次 openclaw 消失的直接原因就是 npm prefix 落在 Kimi 桌面版共享目录，被升级清掉。独立 prefix 从根上消除此类耦合
- **备选**：继续用 Kimi 内嵌 node —— 否决，同一隐患会重演；nvm-windows —— 单机单版本场景无必要

### D2: 安装 openclaw@2026.7.1 而非最新版

- **决定**：`npm i -g openclaw@2026.7.1`，与 `openclaw.json` 的 `meta.lastTouchedVersion: 2026.7.1-2` 对齐
- **理由**：版本对齐可最大限度保证既有配置（含 weixin 渠道状态、sqlite）无损复用
- **备选**：装最新版让 openclaw 自动迁移配置 —— 有迁移失败风险；待最小尝试跑通后可单独评估升级

### D3: Kimi provider 作为新增 provider 而非替换

- **决定**：在 `models.providers` 中新增 `kimi-coding` provider：

  ```json
  "kimi-coding": {
    "baseUrl": "https://api.kimi.com/coding/v1",
    "api": "openai-completions",
    "apiKey": "<Kimi For Coding Key>",
    "models": [{ "id": "k3-256k", ... }, { "id": "kimi-for-coding", ... }]
  }
  ```

  并将 `agents.defaults.model.primary` 切到 `kimi-coding/k3-256k`；zhehentiaohe 配置原样保留
- **理由**：保留 fallback 可在 key 失效/限频时秒切回；`k3-256k`（262k ctx）比 `k3`（1M ctx）更省订阅窗口额度，适合监视类高频小任务；`supports_thinking_type: "only"` 表明这些模型强制 thinking，配置中 `reasoning` 字段按 openclaw 对该 api 类型的要求设置
- **备选**：`openclaw onboard --auth-choice moonshot-api-key` 交互式配置 —— 该向导面向 platform.moonshot.cn 端点，与本 key 的实际端点（api.kimi.com/coding）不符，手写 JSON 更直接

### D4: 密钥管理

- **决定**：Key 只写入 `~/.openclaw/openclaw.json`；任何文档/报告/openspec 工件中只出现掩码形式；修改配置前先 `cp openclaw.json openclaw.json.bak.setup-kimi`
- **理由**：Key 已在聊天记录中暴露过一次，缩小后续暴露面；建议用户事后在会员页轮换

### D5: Kimi 插件关联作为可选验证项

- **决定**：主目标完成后，用无会员账号尝试 kimi.com/bot → 关联已有 OpenClaw；记录结果（成功/被会员门槛拦截）
- **理由**：官方文档只明确"一键部署"需 Allegretto，"关联已有实例"是否需会员未写明，实测一次即可为后续是否等会员号提供决策依据

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| Kimi For Coding 是订阅额度（时间窗口限频），非按 token 计费 | 高频监视任务可能撞窗口上限 | 主模型选 `k3-256k`；flow1 设计阶段再定轮询频率；保留 fallback |
| openclaw 对 `openai-completions` 类型 + 强制 thinking 模型的兼容性未实测 | 冒烟可能失败 | 失败时依次尝试 `kimi-for-coding`、调整 reasoning 配置、查看 gateway 日志定位 |
| 重装 openclaw 后 weixin 渠道需重新配对 | 个人微信渠道中断 | 该渠道非最小尝试必需；坏了也不阻塞主目标，记录即可 |
| winget/官网安装 Node 需要网络与管理员确认弹窗 | 安装中断 | 用户已授权；失败则退用便携版 Node.zip 解压到 `C:\Tools` |
| Kimi 插件关联需扫码/网页登录，可能要求会员 | 可选项目标失败 | 明确记录结果，不阻塞 |
