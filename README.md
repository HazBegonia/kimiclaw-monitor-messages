# kimiclaw-monitor-messages

内网信息监控系统：轮询内网页面 → 规则过滤重要性 → 企业微信群推送。核心链路纯 Python、无 LLM 依赖；可选叠加 Kimi Claw（OpenClaw），直接在群里 @机器人 提需求变更。

```
【推送链路】
内网页面 ──轮询──> 采集器 ──> 本地日志（diff/版本快照/错误）
                             │
                             ▼
                          通知器 ──规则判定──> 聚合 markdown
                             │
                             ▼
                    企业微信智能机器人长连接 ──> 目标群

【需求链路（OpenClaw）】
群里 @机器人 ──> Claw gateway ──草案协议──> 改写 config/*.json
                                                      │
                                                      ▼
                                  采集器/通知器下一轮热读生效
```

## 部署前准备

交付方需要先准备好这三样，缺一个都跑不起来：

| 准备项 | 说明 |
| --- | --- |
| 企业微信智能机器人 | 电脑客户端「工作台 → 智能机器人 → 创建 → API 模式 → **长连接**」，拿到 **BotID + Secret** |
| 目标群 chatid | 把机器人拉进目标群，**群里有人 @机器人 发过一条消息**后，chatid 出现在机器人收到的回调帧里（装了 OpenClaw 的话 `openclaw sessions list` 可直接看到） |
| 一台 Linux 机器 | 能访问被监控的内网页面，且能出网连 `wss://openws.work.weixin.qq.com`（443）；Python ≥ 3.11 |

注意事项：

- ⚠️ **同一 botId 连接独占**：一个机器人同时只能一处在线。不要用同一个机器人凭证部署第二套，也不要和企业微信客户端里正在调试的会话并存。
- 机器人被移出群再加回后，需要重新 @机器人 并核对 chatid。
- 可选组件：Node ≥ 22 + OpenClaw（仅用于"群里 @机器人 提需求"的交互入口；不装则监控+推送完全照常）。

## 快速部署

```bash
# 1. 获取代码
git clone <仓库地址> && cd kimiclaw-monitor-messages   # 或直接解 tar 包

# 2. 一键安装：建 Python 环境、装依赖、从模板生成 config、装 systemd unit 并启动
scripts/linux/install.sh
#    可选参数：--python /path/to/python  指定解释器（默认优先 conda env，其次建 .venv）
#             --no-start               只安装不启动

# 3. 填写机器人凭证（install.sh 已从模板生成空文件）
vim state/secrets/wecom-bot.json
#    { "botId": "你的BotID", "secret": "你的Secret" }

# 4. 按实际环境编辑 config/ 下四个文件（见下节「配置说明」）

# 5. 改完重启生效（配置本身热读，但凭证是连接时读的，首次填好后重启一次最稳妥）
systemctl --user restart kimiclaw-monitor kimiclaw-notifier
```

需要开机自启、注销不掉：

```bash
loginctl enable-linger <用户名>
```

## 配置说明

| 文件 | 要改什么 | 说明 |
| --- | --- | --- |
| `monitors.json` | `url` 改成实际内网页面地址 | 监控目标清单；`profile` 描述页面结构（如只认 `.csv` 链接），多目标可加多项 |
| `notifier.json` | `chatid` 填目标群、`sourceUrl` 填内网页面地址 | 通知器主配置；其余字段（目录、超时）一般保持默认 |
| `intranet-versions.json` | `match` 填关注的版本号/字段 | 命中字段的文件集合变化时额外记版本快照；空数组 `[]` = 停用该功能 |
| `triage-rules.json` | 按需调整 | 重要性规则：新增/删除文件默认推、错误推送类型、文件名 suppress/include 过滤。默认值即可跑 |

## 部署后验证

```bash
# 1. 渲染预览：只打印将要推送的内容，不发送、不推进游标
python -m src.intranet_notifier --once --dry-run

# 2. 单轮真实发送（失败退出码非 0）
python -m src.intranet_notifier --once

# 3. 看服务状态与日志
systemctl --user status kimiclaw-monitor kimiclaw-notifier
journalctl --user -u kimiclaw-notifier -f

# 4.（可选）跑测试自检
pip install -r requirements-dev.txt && pytest
```

## @机器人 提需求

装上机器人后可以在群里 @机器人 用自然语言提需求（改监控目标、加关注版本、调过滤规则），由 Claw 按 `skills/ff-config-assistant` 的草案协议代笔改写 config（起草 → 群内回显 → 逐字「写入」确认 → 落盘 → 校验，失败自动回滚）。

部署要求：

1. Node ≥ 22，`npm i -g openclaw`
2. 安装企微插件 `wecom-openclaw-plugin` 与 `@openclaw/kimi-provider`；kimi-claw 插件需要 Kimi Claw 订阅号环境
3. `~/.openclaw/openclaw.json`：填入同一机器人的 `channels.wecom` 凭证，`skills.load.extraDirs` 指向本仓库 `skills/`
4. 重跑 `scripts/linux/install.sh`（检测到 openclaw 会自动加装 `kimiclaw-openclaw-gateway.service`）

## 文件树

```
kimiclaw-monitor-messages/
├── src/                        # 核心代码
│   ├── intranet_filename_monitor.py   # 采集器：轮询内网页面 → diff/版本快照/错误日志
│   ├── intranet_notifier.py           # 通知器：游标消费 → 规则判定 → 聚合推送
│   ├── triage_rules.py                # 重要性规则引擎（每轮热读规则文件）
│   ├── bot_tool.py                    # 连接编排：借线推送 / 拉活 Claw / 失败退避
│   └── wecom_bot_client.py            # 企微机器人长连接协议层（纯传输）
├── skills/
│   └── ff-config-assistant/SKILL.md   # @机器人 需求变更草案协议（可选 OpenClaw 用）
├── config/                     # 配置（全部热读；*.example.json 为入库模板）
├── scripts/
│   ├── linux/                         # install.sh + 3 个 systemd unit 模板
│   ├── windows/                       # Windows 计划任务脚本（历史回滚保留）
│   └── poc_wecom_ws.py                # 企微长连接单文件 PoC
├── state/                      # 运行态（不入库：游标、心跳锁、草案台账、凭证）
├── logs/                       # 产物日志（diff / 版本快照 / 通知留痕）
├── tests/                      # pytest 自检
├── docs/                       # 现行文档（见下）
├── wiki/                       # 调研存档（KIMICLAW 调研报告、连接独占实测等）
└── openspec/                   # 变更管理（specs/ 现行规格，changes/archive/ 历史）
```