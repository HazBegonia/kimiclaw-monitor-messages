# 任务说明

现在有 3 个信息来源，需要实时从其中抓取重要信息并实时返回到微信或者邮箱里。

信息来源：

- 公司的内部网站（通过内网）
- 企业微信消息
- 钉钉消息


消息可能有很多，有重要的或者不重要的，要过滤不重要的信息，提取出重要的。关于重要性的界定，由公司上级决定。

目前需要部署一个 agent，公司打算使用 `KIMICLAW` 来监测，需要先调研 `KIMICLAW`，然后做进一步方案。

需要调研如下：

- 1、使用 kimiclaw 的前提？
- 2、无 kimi 号（专指Allegretto计划套餐以上，能开通kimiclaw的号）有key能不能配置好kimiclaw？
- 3、kimiclaw 如何获取公司的内网 web、企业微信消息、钉钉消息的信息？
- 4、如何配置 kimiclaw？完成上述任务可行的 workflow？

目前调研完毕，写在了 docs/KIMICLAW调研报告.md 里面。

# 最小尝试

下一步是做最小尝试调查：

由于缺少 kimi 会员号，经讨论决定先改用 openclaw + kimi插件 + kimi 的 key 尝试，等 kimi 号有了再换 kimiclaw。

现在只需要做内网 web 连接测试，先不管企业微信消息和钉钉消息。

## workflow

- flow1：
claw 通过 cron 和 py 脚本监视 web -> 监测到 web 有消息生成 .log 日志文件 -> claw 通过 skill 对消息做信息重要性处理，筛选出重要的消息 -> 企业微信

- flow2：
py 脚本监视 web 的同时记录错误 -> py 脚本写下 .log 文件，记录异常，生成原始错误日志 -> claw 读取错误日志 -> 通过 claw 的 skill 来判断这个错误对影响业务的重要性 -> 发现重要则发送到企业微信

目前公司需要监视的内网 web 的 url 为[Directory listing for /](http://172.16.30.20:8011/)（本机可以直接访问）；

## 发送渠道现状（2026-09-11 起）

flow1/flow2 的"发送到企业微信"已落地：OpenClaw 官方插件 `@wecom/wecom-openclaw-plugin` 接入智能机器人 **FF**（长连接模式，不需要域名备案和可信IP），推送到测试企业「未命名企业」的全员群（李非凡在群内）。

- 扫描任务 `intranet-file-monitor-once`（每分钟写日志）+ 通知任务 `intranet-message-notify`（每分钟 agent triage+推送），均由 `scripts/register-openclaw-intranet-cron.ps1` 注册。
- 重要性判定规则见 `.agents/skills/intranet-message-triage/SKILL.md`；推送游标在 `state/notify-state.json`；推送失败记录在 `logs/intranet-notify/`。
- Bot ID/Secret 只存全局 `~/.openclaw/openclaw.json`，仓库内禁止明文密钥；群 chatId 等脱敏配置在 `config/wecom-aibot.json`。
- 前提：目标群里须有人 @FF 发过消息机器人才能主动推送；失效时重新 @FF 并核对 chatId。

约束：本机生成的任何文件都要放在 C:\Users\ELadmin\Desktop\program\kimiclaw-monitor-messages 这里，全局配置除外。