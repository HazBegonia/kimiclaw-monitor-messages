# Tasks: wecom-aibot-notify

## 1. 渠道接入与冒烟

- [x] 1.1 安装官方插件 `openclaw plugins install @wecom/wecom-openclaw-plugin` 并重启 gateway
- [x] 1.2 `openclaw channels add` 选择企业微信，填入 FF 的 Bot ID/Secret，完成 Pairing 配对（需用户贴回企微收到的配对密钥）
- [x] 1.3 确认渠道在线：gateway 日志出现长连接建立成功，`openclaw channels` 列表可见企微渠道
- [x] 1.4 用户在全员群 @FF 发送一条消息激活会话；从渠道回调解析群 chatid
- [x] 1.5 新建 `config/wecom-aibot.json` 保存 chatid 等脱敏配置；自查仓库无明文 Secret
- [x] 1.6 冒烟：通过渠道向 chatid 主动推送一条 markdown 测试消息，李非凡确认群内收到；若插件不支持主动推送则立即评估回退方案（design.md D1）

## 2. Triage skill 补全

- [x] 2.1 补全 `.agents/skills/intranet-message-triage/SKILL.md`：重要性规则初稿（新增/删除 .csv = 重要；监控器自身错误 = 重要；无变化 = 不发送），输入（diff/error 日志位置与格式）、输出（聚合 markdown 文本 + 是否发送结论）
- [x] 2.2 用 `state/demo-state-1519.json` 与历史 `logs/` 样例离线演练 triage，确认聚合格式与判定行为符合预期

## 3. 链路接入

- [x] 3.1 flow1：cron 轮次中，claw 读取本轮 `logs/intranet-diff/` 产物 → triage 判定 → 重要则经企微渠道推送聚合消息到全员群
- [x] 3.2 flow2：同轮次读取 `logs/intranet-error/` 新增错误记录 → triage 判定 → 重要则推送（含错误阶段与脱敏摘要）
- [x] 3.3 推送失败处理：失败原因与消息摘要写入本地日志（`logs/` 下新增 notify 类日志），不中断扫描流程
- [x] 3.4 频控护栏：单轮仅发送聚合后的一条消息；异常大量变更时截断列表并注明条数

## 4. 端到端验证

- [x] 4.1 向内网目录投放测试 csv → 一个 cron 周期内群内收到告警
- [x] 4.2 制造一次扫描错误（如临时断网/改错 URL 配置）→ 群内收到错误告警，随后恢复
- [x] 4.3 无变化轮次不产生任何推送
- [x] 4.4 `git status` 与仓库全文检索确认无明文 Secret

## 5. 文档与收尾

- [x] 5.1 更新 `docs/workflow.md`：发送渠道、激活前提、频控、恢复步骤（chatid 失效时重新 @FF）
- [x] 5.2 更新 `docs/intranet-file-monitor.md` 与 `AGENTS.md`：flow1/flow2 末端描述从"企业微信"具体化为 FF 机器人渠道
- [x] 5.3 更新 `wiki/log.md`：记录本次实施要点
- [x] 5.4 提醒用户重置机器人 Secret（曾在聊天中明文出现），重置后更新渠道配置
