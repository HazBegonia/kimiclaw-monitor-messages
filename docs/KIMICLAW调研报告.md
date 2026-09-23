# KimiClaw 调研报告

> 调研日期：2026-09-01（已补充 Kimi 官方帮助中心文档；已补充企业微信/钉钉具体接入方法）
> 调研目的：评估使用 KimiClaw 监控 3 个信息来源（公司内网网站、企业微信消息、钉钉消息），过滤重要信息并实时推送到微信/邮箱的可行性。
> 说明：结论标注来源与置信度（【官方】= Kimi/企微/钉钉/OpenClaw 官方文档，【实测】= 媒体实测，【推断】，【未找到】），不确定项见文末。

## 〇、KimiClaw 是什么

**KimiClaw（官方写法 "Kimi Claw"）是月之暗面于 2026 年 2 月中旬推出的托管 AI Agent 服务**。官方定义：「Kimi Claw 是一个拥有独特人设和持久长期记忆的 AI 助手。通过 Kimi Claw，你可以直接在 Kimi 中创建、部署并与你自己的 OpenClaw 实例对话。」（[官方概览页](https://www.kimi.ai/help/kimi-claw/overview) 原文）——本质是把开源 Agent 框架 OpenClaw 搬上 Moonshot 云端，一键创建、无需服务器和 API Key。

- 产品入口：https://www.kimi.com/bot
- 官方帮助中心：https://www.kimi.ai/zh-hans/help/kimi-claw （共 15 篇文档，已全部通读）
- **不是开源项目，无官方 GitHub 仓库**；GitHub 上的 "kimiclaw" 同名仓库均为无关个人项目。

## ⚠️ 核心结论（先看这条）

**企业微信智能机器人和钉钉机器人在群聊里都只能收到「@机器人」的消息，收不到群内全量消息；单聊才是全收。**（企微官方文档原文：「用户在群聊中@机器人或向机器人发送单聊消息时，企业微信推送消息回调」；钉钉官方文档同口径）【两平台官方证实】

因此"机器人潜伏在群里监听所有消息 → 过滤 → 推送"用官方机器人通道**做不到**。全量监控的可行路径：

- **企业微信群**：唯一官方全量途径是「**会话内容存档**」API——超级管理员在管理后台付费开通（合规存档，需告知成员），SDK 拉取存档范围内成员的内外部群全部消息，轮询式而非实时推送。【企微官方文档】
- **钉钉群**：**没有任何官方全量消息 API**。只有社区灰色方案（如 ClawHub 的 dingtalk-auto-reply，基于 dws CLI 读未读会话），稳定性和合规性自担。
- 或者改变交互模式：约定同事在群里 **@机器人** 汇报/触发，机器人只处理 @消息。

## 一、使用 KimiClaw 的前提

1. **会员门槛（官方原文）**：「一键部署需要 **Allegretto 或更高**会员方案。」（概览页、Desktop 页）档位：Andante ¥49 / Moderato ¥99 / Allegretto ¥199 / Allegro ¥699 每月。
   - ⚠️ 官方黑板报 2026-07-20 公告原文：「**新套餐暂未开放购买**……受算力限制，新套餐目前暂未开放，具体开放时间待定」；「老套餐未移除，现有用户不受影响」「老用户可升级套餐」。**开通前必须先确认套餐是否恢复售卖。**【官方】
2. **Kimi 账号**：官方文档未提及实名/企业认证要求，前提只有"Kimi 账号 + Allegretto 会员"。
3. **客户端/设备【官方】**：云端模式浏览器即可；Desktop 本地模式需 macOS 或 Windows；Android 模式需 Android 8.0+、5GB 存储。
4. **实例名额（官方原文）**：「每个账号同一时间最多支持 1 个 Kimi Claw Desktop。」
5. **额度/限频【官方】**：消耗会员额度与 API 速率限制；限频时「前往 kimi.com/code → 控制台 → 查看配额和速率限制」，官方建议拉开任务间隔或升级会员。
6. **平台侧权限**：企微智能机器人普通成员可建（电脑客户端）；**钉钉应用必须企业管理员/开发者权限**；企微会话存档必须超管付费开通。

## 二、没有会员号、只有 API Key，能不能用？

**结论：不能开通 KimiClaw 本体，但存在官方允许的等效替代路径。**

- 官方开通路径就是「kimi.com/bot 登录 → 点 Create → 等待自动部署」，全程无 API Key 填写环节；官方明确「Kimi 会自动配置 Kimi K2.6 模型，并关联你的 Kimi 会员权益额度……无需单独配置 API」。【官方】
- **替代路径：自建 OpenClaw + Kimi 开放平台 API Key**（platform.moonshot.cn）：
  - 交互式：`openclaw onboard --auth-choice moonshot-api-key`
  - 或 `~/.openclaw/openclaw.json` 设 `MOONSHOT_API_KEY`，模型选 `Moonshot/Kimi-K2.5` 等
  - 或 OpenAI 兼容模式：`base_url=https://api.moonshot.cn/v1`
  - 【社区教程，多篇一致】
- 官方支持把自建实例接回 Kimi：「如果你已经自行托管了 OpenClaw 实例，可以**安装 Kimi 插件**将它连接到 Kimi：kimi.com/bot → 关联已有 OpenClaw → 按说明安装插件 → 连接后即可通过 Kimi 与你的 OpenClaw 对话。」（概览页原文）【官方】
- 差异【36氪实测】：自建是"裸模型 + 原生 OpenClaw"，无 Kimi 官网版搜索增强，但**无云端沙箱限制**；Token 按 API 计费（参考：每小时一次监控任务 ≈ ¥330/月）。

即：**只有 Key 没有会员 → 可以做同样的事，但那是自建 OpenClaw（可再挂回 Kimi），不是 KimiClaw 托管服务。**

## 三、三个信息源的接入方法（详细）

### 官方渠道边界（前提性说明）

Kimi 官方「支持的平台」页原文：「Kimi Claw 目前支持以下平台：**网页端、移动端（iOS/Android Kimi App）、Telegram**。更多平台集成正在规划中。」——**Kimi 官方文档背书的渠道只有 Telegram**；微信、飞书仅 Kimi Claw Android 版支持。OpenClaw 官方渠道列表（docs.openclaw.ai/channels）也**不含企业微信和钉钉**。下面 3.1/3.2 的接入来自**平台官方方案 + OpenClaw 生态插件**，可用但 Kimi 官方未背书。

### 3.1 企业微信消息 ✅（腾讯官方插件 + 企微官方长连接方案）

**接入步骤**（腾讯官方插件 `@wecom/wecom-openclaw-cli`，npm 可查，2026-03 发布；步骤经插件 README 与多篇教程交叉验证）：

1. 企业微信侧创建**智能机器人**：电脑客户端「工作台 → 智能机器人 → 创建 → 手动创建 → 底部切 **API 模式 → 长连接**」（普通成员可创建；管理员也可后台创建），拿到 **BotID + Secret**（长连接专用密钥）；
2. OpenClaw 侧安装插件：`npx -y @wecom/wecom-openclaw-cli install`（交互式输入 BotID/Secret），然后 `openclaw gateway start` 重启；诊断命令 `npx -y @wecom/wecom-openclaw-cli doctor`；
3. 配对：在企微机器人对话框把配对码发给 OpenClaw，完成双向绑定。

**技术机制**（[企微官方文档《智能机器人长连接》](https://developer.work.weixin.qq.com/document/path/101463)，全文已核）：

- WebSocket 长连接 `wss://openws.work.weixin.qq.com`，`aibot_subscribe` 订阅；**无需公网 IP、无需消息加解密**，内网机器出站即可；
- 每个机器人同时只能保持 1 个长连接（新连接踢旧连接）；官方提供 aibot-node-sdk / aibot-python-sdk；
- **收消息范围：群里只收 @机器人 的消息；单聊全收**；消息类型：文本/图文混排群聊单聊都行，**图片、语音、文件、视频仅单聊支持**；
- **主动推送**：`aibot_send_msg`，支持单聊（userid）和群聊（chatid），**前提是用户在会话中给机器人发过消息**；限额 **30 条/分钟、1000 条/小时每会话**；推送支持 markdown、模板卡片、文件、图片等；
- 注意：事件中 `from.userid` 默认是加密的，除非机器人创建者是超管或关联自建应用——做"按人过滤"时要处理。

**两个企微通道的选型**：

| 通道 | 收 | 发 | 监控场景定位 |
|---|---|---|---|
| 群机器人 webhook（key 型） | ❌ 完全不能收 | ✅ 20 条/分钟 | 只做**推送出口** |
| 智能机器人（长连接） | 群 @ + 单聊 | 30 条/分钟/会话，需先交互 | **交互/过滤入口 + 推送** |
| 会话内容存档 API | ✅ 全量（轮询拉取） | — | **全量监控唯一官方途径**（超管付费开通） |

### 3.2 钉钉消息 ✅（钉钉开放平台 + ClawHub 插件）

**接入步骤**（钉钉官方文档 + 多篇教程交叉验证）：

1. 钉钉开发者后台（open-dev.dingtalk.com）创建**企业内部应用**——**必须企业管理员或开发者权限，普通成员不行**；
2. 给应用添加「机器人」能力，消息接收模式选 **Stream 模式**（官方推荐：WebSocket 长连接，**无需公网 IP/域名**，适合内网部署）或 HTTP 回调（需公网地址）；
3. 拿 **Client ID（AppKey）/ Client Secret（AppSecret）**，开通权限（企业内机器人发消息、成员信息读权限等），发布应用；
4. OpenClaw 侧装钉钉渠道插件（ClawHub 有 20+ 个，**选型注意**：chayjan 的 Dingtalk channel 插件 3.6k 下载但需要**公网回调 URL**，内网部署应选**社区 Stream 模式插件**——WebSocket 长连接免公网，支持私聊、群@、文本/图片/语音/视频/文件）；配置环境变量 `DINGTALK_CLIENT_ID` / `DINGTALK_CLIENT_SECRET`，含 `dmPolicy`/`groupPolicy`/`groupAllowFrom` 等策略字段；
5. 重启 gateway，群内 @机器人或单聊即可交互。

**关键限制**（钉钉官方文档口径）：

- **收消息范围：群里只收 @机器人 的消息，单聊全收**，Stream/HTTP 两种模式相同；
- **没有"读群全量消息"的官方 API**；钉钉 MCP 广场（mcp.dingtalk.com）的官方 MCP server 偏文档/日程/表格，**没有读群消息的 MCP**；
- 推送限额：群 webhook 加签机器人 **20 条/分钟**（超限限流 10 分钟）；企业工作通知 **同一员工每天最多 500 条**、相同内容一天只能发一次。

### 3.3 OpenClaw 侧的通用机制（配置时直接用）

- 渠道配置统一在 `~/.openclaw/openclaw.json` 的 `channels.<渠道id>` 段；群聊默认 `requireMention`（要求 @），可配 `allowFrom` 白名单、`dmPolicy`/`groupPolicy` 策略。【OpenClaw 官方文档】
- **Hooks**：官方支持 `message:received` 等事件挂自定义 handler（`~/.openclaw/hooks/`），可在任何渠道入站消息时执行过滤/转发。【官方】
- **Webhooks**：官方支持外部 HTTP 端点触发 OpenClaw 任务——任何自研监控系统都可以 HTTP POST 给 Gateway 触发 agent。【官方】
- 兜底形态：脚本轮询平台 API（企微会话存档等）→ 由 HEARTBEAT 定时任务执行过滤；或 n8n/腾讯 HiFlow 等连接器桥接。

## 四、配置方式与可行 Workflow

### 4.1 官方基础流程

1. 订阅 Allegretto ¥199/月以上会员（先确认新套餐是否恢复售卖，见第一节⚠️）；
2. kimi.com/bot 创建实例——本场景建议 **Kimi Claw Desktop 部署到一台能访问内网的常驻机器**（或自建 OpenClaw + BYOC）；
3. 自然语言定义助手人设与过滤规则（重要性标准由上级决定，**务必写入记忆/文件**——见 4.2）；
4. 安装技能与渠道插件（企微插件、钉钉 Stream 插件）；
5. 按 3.1/3.2 完成渠道配对。

### 4.2 官方机制要点（配置时直接相关）

- **定时任务 = HEARTBEAT**【官方】：「按定时器运行的计划后台任务，适用于周期性提醒、数据拉取和摘要汇总」。官方技巧：「把任务安排在非整点时间（如 9:17 而不是 9:00），以避开高峰拥堵」。
- **记忆机制【官方】**：「OpenClaw 会在**每天凌晨 4:00 自动重置会话**」，存入记忆（工作空间 `AGENTS.md → #MEMORY`）的信息跨重置保留，可用 `/memory` 管理。**过滤规则不落进记忆就会每天丢失。**
- **订阅到期【官方】**：「会员到期后，云端实例会保留 7 天。7 天内续费数据完整恢复；超过 7 天实例可能被回收，数据永久删除。」记忆导出/备份功能官方称"正在开发中"。
- 故障排查官方错误码：401 重新登录、403 会员等级不足、429 超速率限制。

### 4.3 推荐 Workflow（本地模式）

```
[内网常驻机器：Kimi Claw Desktop / 自建 OpenClaw + Kimi 插件]
        │
        ├─ HEARTBEAT 定时任务：抓公司内网网站更新（本地直连，避开整点）
        ├─ 企业微信（二选一或并行）：
        │    a. 会话内容存档 API 轮询 → 全量群消息（需超管付费开通）
        │    b. 智能机器人长连接 → 收 @消息/单聊（腾讯官方插件）
        ├─ 钉钉：Stream 模式机器人 → 收 @消息/单聊
        │       （全量群消息无官方 API，只能约定 @机器人 或用灰色方案）
        │
        ▼
   K2.6 模型按预设规则过滤/摘要（规则写入 MEMORY 防每日重置）
        │
        ▼
   推送出口（按可靠性排序）：
   ① 企业微信群机器人 webhook —— 只发不收，20 条/分钟，最稳 ✅
      或智能机器人主动推（30 条/分钟/会话，需先有过交互）
   ② 钉钉群 webhook 加签机器人 —— 20 条/分钟 ✅
   ③ 邮件 —— SMTP 技能/脚本 ⚠️需实测
   ④ 个人微信 —— 仅 Android 版经 WeChat Claw 扫码，有封号风险，
      生产环境不建议作主通道 ⚠️
```

### 4.4 推送出口说明

- **推送到"微信"的最稳妥实现 = 企业微信群机器人 webhook**（员工在企微群接收）。个人微信仅 Android 版支持（官方原文：「微信渠道需要先在微信端安装 WeChat Claw……使用微信扫描二维码完成流程」），且有账号风险。【官方+推断】
- **邮箱推送**：Kimi 官方文档无 SMTP 条目；ClawHub 有 SMTP 发信技能实践，本地模式等同本机跑脚本调 SMTP，可行性高。【社区实践+推断】

## 五、风险与注意事项

1. **群消息全量监控受阻（最大功能风险）**：企微/钉钉官方机器人群里都只收 @消息。企微全量需会话存档 API（超管+付费+告知成员的合规流程）；钉钉全量无官方途径。【两平台官方证实】
2. **数据合规**：消息内容会发给 Moonshot 模型 API，公司内网信息、企微/钉钉消息将离开企业边界；若再叠加企微会话存档，敏感面更大。涉密场景需先过安全/合规评审。
3. **新套餐暂停售卖**：2026-07-20 官方公告因算力限制暂停新套餐购买。【官方】
4. **云端沙箱限制**：媒体实测云端实例浏览器自动化、系统级操作、部分主动外发不可用；本地/Desktop 模式无此限制。
5. **实例限制**：每账号同时仅 1 个 Desktop 实例【官方】。
6. **渠道背书**：企微/钉钉接入非 Kimi 官方文档支持，依赖腾讯官方插件/ClawHub 社区插件，升级兼容性需自行验证；钉钉社区 Stream 插件质量参差。
7. **Beta 稳定性**：2026-04 曾出现排队、额度误扣，官方致歉补偿。

## 六、结论

| 调研问题 | 结论 |
|---|---|
| 1. 使用前提 | Kimi 账号 + Allegretto ¥199/月以上会员（官方原文）；Desktop 需 macOS/Windows + 每账号限 1 实例；**⚠️ 新套餐目前暂停售卖（2026-07-20 官方公告）** |
| 2. 只有 Key 无会员 | **不能开通 KimiClaw**；可自建 OpenClaw + Moonshot API Key（官方允许，可装 Kimi 插件接回 Kimi），但非同一产品 |
| 3. 三源接入 | 内网网站 ⚠️ 必须 Desktop/BYOC 本地模式；企微 ✅ 官方插件+长连接机器人，**但群里只收 @消息**，全量需会话存档 API（超管付费）；钉钉 ✅ Stream 机器人可接，**同样只收 @消息**，且全量无官方 API |
| 4. 可行 workflow | Desktop 常驻内网机器 + HEARTBEAT 定时抓内网 + 企微存档轮询/长连接监听 + 钉钉 Stream 监听 + K2.6 过滤（规则入 MEMORY）+ 企微/钉钉 webhook 群机器人推送；**技术可行，但"钉钉群全量监控"这一条没有合规实现路径**，落地前还需解决①套餐购买②数据合规审批 |


## 主要来源

- Kimi 官方概览：https://www.kimi.ai/help/kimi-claw/overview ；帮助中心 15 篇：https://www.kimi.ai/zh-hans/help/kimi-claw
- Kimi 官方黑板报《会员订阅套餐调整说明》2026-07-20：https://www.kimi.ai/zh-hans/help/kimi-blackboard/plan-adjustment-notice
- 企业微信官方文档《智能机器人长连接》：https://developer.work.weixin.qq.com/document/path/101463
- 企业微信官方 OpenClaw 插件：npm `@wecom/wecom-openclaw-cli`（插件包 `@wecom/wecom-openclaw-plugin`）
- 钉钉开放平台：https://open.dingtalk.com/document/dingstart/configure-the-robot-application ；开发者后台 open-dev.dingtalk.com ；MCP 广场 mcp.dingtalk.com
- OpenClaw 官方文档：https://docs.openclaw.ai/zh-CN （channels / automation/hooks）；技能库：https://clawhub.com
- 36氪实测：https://www.36kr.com/p/3702801991970948 ；搜狐实测：https://www.sohu.com/a/990578142_121124376
- 企业微信 OpenClaw 接入报道：时代财经/北京商报 2026-03-09、财联社 2026-03-14
