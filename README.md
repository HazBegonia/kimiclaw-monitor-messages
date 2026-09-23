# kimiclaw-monitor-messages

内网信息监控 → 重要性过滤 → 企业微信群推送。核心链路纯 Python、**0 token**;可选叠加 Kimi Claw(OpenClaw)接收上级在群里 @机器人 提出的需求变更。

```
内网页面 ──轮询──> 采集器 ──> 本地日志(diff/版本快照/错误)
                              │
                              ▼
                           通知器 ──规则判定(config/triage-rules.json)──> 聚合 markdown
                              │
                              ▼
                     企业微信智能机器人长连接 ──> 目标群
```

## 前置条件:Python ≥ 3.11 + 自己的企微机器人

- Linux(systemd user session)+ **Python ≥ 3.11**;唯一第三方依赖 `websocket-client`
- **自己的企业微信智能机器人**:电脑客户端「工作台 → 智能机器人 → 创建 → API 模式 → 长连接」,拿 BotID + Secret
  - ⚠️ **同一 botId 连接独占**:一个机器人同时只能一处在线,别和其他部署共用凭证
  - 目标群里须先有人 @机器人 发过消息,机器人才能主动推送
- 可选:Node ≥ 22 + OpenClaw + 企微插件(仅用于 @机器人 需求交互;不装则监控+推送照常,只是没有"群里提需求"入口)

## 快速开始

```bash
# 1. 获取代码
git clone <仓库地址> && cd kimiclaw-monitor-messages   # 或直接解 tar 包

# 2. 安装(建环境、装依赖、生成 config、装 systemd unit 并启动)
scripts/linux/install.sh            # --python /path/to/python 指定解释器;--no-start 只装不启

# 3. 填写凭证(安装脚本已放模板)
vim state/secrets/wecom-bot.json    # botId / secret

# 4. 按实际环境编辑 config/(install.sh 已从 *.example.json 生成)
#    - monitors.json          监控目标 URL
#    - notifier.json          目标群 chatid、内网 sourceUrl
#    - intranet-versions.json 关注的版本号清单(空数组=停用版本快照)
#    - triage-rules.json      重要性规则,通知器每轮热读

# 5. 验证
python -m src.intranet_notifier --once --dry-run   # 渲染预览,不发送不推游标
pip install -r requirements-dev.txt && pytest       # 自检(可选)
systemctl --user status kimiclaw-monitor kimiclaw-notifier
```

需要开机自启/注销不掉:`loginctl enable-linger <用户名>`。

## 文档

| 文档                            | 内容                                                  |
| ------------------------------- | ----------------------------------------------------- |
| `docs/architecture.md`          | 现行架构:链路、组件、单 FF 错峰共用、规则、游标、回滚 |
| `docs/operations.md`            | 运维手册:启停、配置速查、排障顺序、回滚 Windows       |
| `docs/intranet-file-monitor.md` | 采集器细节:目标配置、三类产物、限制                   |
| `docs/linux-deployment.md`      | 本项目的实际部署记录(FF 服务器环境清单)               |
| `wiki/`                         | 调研存档与实测结论(连接独占、KimiClaw 调研报告)       |

## 入库约定

- `config/*.json`、`state/` 不入库(含部署私有信息);入库的只有 `config/*.example.json` 模板,`install.sh` 负责首次生成
- 凭证只放 `state/secrets/wecom-bot.json`,仓库内禁止明文密钥
- 规则/配置均为人工直改、下一轮热读生效,无自动派生机制
