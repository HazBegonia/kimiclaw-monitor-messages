# Wiki Log

## 2026-09-11 · wecom-aibot-notify 实施完成

- 安装 `@wecom/wecom-openclaw-plugin`，以智能机器人 FF（长连接）建立企微渠道；Bot ID/Secret 入全局 `~/.openclaw/openclaw.json`。
- 凭证排障：Secret 从截图 OCR 得到 `28Qn0w`（数字0），正确为 `28QnOw`（字母O），errcode 853000；另需机器人创建者在「工作台-智能机器人」授权「消息」权限（errcode 850002），授权后 `sessions list` 可用。
- 会话激活：李非凡在全员群 @FF 后发一条消息，取得群 chatId，存 `config/wecom-aibot.json`（脱敏）。
- 补全 `.agents/skills/intranet-message-triage/SKILL.md`（判定规则、聚合模板、游标/失败处理）；`register-openclaw-intranet-cron.ps1` 新增注册 `intranet-message-notify` agent 任务（每 1m）。
- 端到端验证：首轮推送 80 个新增 csv 的聚合告警；3 条同 phase 拉取错误触发错误告警；空闲轮次不推送；游标正常推进。
- 注意：PowerShell 脚本必须保持 UTF-8 with BOM（编辑器重写后需检查文件头 EF BB BF）。

