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

| 准备项             | 说明                                                                                                                                                 |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 企业微信智能机器人 | 电脑客户端「工作台 → 智能机器人 → 创建 → API 模式 → **长连接**」，拿到 **BotID + Secret**                                                            |
| 目标群 chatid      | 把机器人拉进目标群，**群里有人 @机器人 发过一条消息**后，chatid 出现在机器人收到的回调帧里（装了 OpenClaw 的话 `openclaw sessions list` 可直接看到） |
| 一台 Linux 机器    | 能访问被监控的内网页面，且能出网连 `wss://openws.work.weixin.qq.com`（443）；Python ≥ 3.11                                                           |

注意事项：

- ⚠️ **同一 botId 连接独占**：一个机器人同时只能一处在线。不要用同一个机器人凭证部署第二套，也不要和企业微信客户端里正在调试的会话并存。
- 机器人被移出群再加回后，需要重新 @机器人 并核对 chatid。
- 可选组件：Node ≥ 22 + OpenClaw（仅用于"群里 @机器人 提需求"的交互入口；不装则监控+推送完全照常）。

## 快速部署

```bash
# 1. 获取代码
git clone <仓库地址> && cd kimiclaw-monitor-messages   # 或直接解 tar 包

# 2. 准备 Python 环境（二选一）
#    a. conda（推荐，与 FF 服务器一致）：
conda create -y -n kimiclaw-monitor-messages python=3.11
#    b. 没有 conda 就跳过这步，install.sh 会在仓库下自动建 .venv

# 3. 一键安装：装依赖、从模板生成 config、装 systemd unit 并启动
scripts/linux/install.sh
#    用了 conda 时指定解释器：
#    scripts/linux/install.sh --python "$(conda run -n kimiclaw-monitor-messages python -c 'import sys; print(sys.executable)')"
#    其他可选参数：--no-start 只安装不启动
#    不指定 --python 时 install.sh 自动探测：已有 conda env kimiclaw-monitor-messages → 用它；否则建 .venv

# 4. 填写机器人凭证（install.sh 已从模板生成空文件）
vim state/secrets/wecom-bot.json
#    { "botId": "你的BotID", "secret": "你的Secret" }

# 5. 按实际环境编辑 src/.env 和 config/ 下的 JSON 文件（见下节「配置说明」）

# 6. 改完重启生效（配置本身热读，但凭证是连接时读的，首次填好后重启一次最稳妥）
systemctl --user restart kimiclaw-monitor kimiclaw-notifier
```

需要开机自启、注销不掉：

```bash
loginctl enable-linger <用户名>
```

## 配置说明

常量值放在 `src/.env`，结构化业务配置放在 `config/*.json`：

| 文件                            | 要改什么                                                                                 | 说明                                                                                      |
| ------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `src/.env`                      | `DEFAULT_URL`、`DEFAULT_INTERVAL`、`DEFAULT_TIMEOUT`、`TIME_ZONE`、日志/锁路径、渲染限制 | 模块加载时读取，修改后重启对应服务                                                        |
| `config/monitors.json`          | `url` 改成实际内网页面地址                                                               | 监控目标清单；`profile` 描述页面结构（如只认 `.csv` 链接），多目标可加多项                |
| `config/notifier.json`          | `chatid`、`sourceUrl`、`templateFile`                                                    | 通知器 JSON 配置                                                                          |
| `config/notify-template.json`   | 标题、来源、区块、列表项和提示文案                                                       | 通知器每次发送前重新读取并填充模板                                                        |
| `config/intranet-versions.json` | `match` 填关注的版本号/字段                                                              | 命中字段的文件集合变化时额外记版本快照；空数组 `[]` = 停用该功能                          |
| `config/triage-rules.json`      | 按需调整                                                                                 | 重要性规则：新增/删除文件默认推、错误推送类型、文件名 suppress/include 过滤。默认值即可跑 |

代码通过 `python-dotenv` 直接读取 `src/.env`，再用 `os.getenv()` 取得常量；系统环境变量优先。机器人凭证仍只放在 `state/secrets/wecom-bot.json`，不放进 `.env`。

消息模板使用 `{{变量}}` 占位：

- 标题：`{{timestamp}}`；来源：`{{sourceUrl}}`。
- 区块标题：`{{count}}`；列表项：`{{item}}`；超额提示：`{{omitted}}`、`{{count}}`。
- 错误摘要：`{{time}}`、`{{phase}}`、`{{errorType}}`、`{{message}}`。
- `sections` 数组决定区块及其顺序。删除整个 `type: "errors"` 对象后，通知不再包含错误标题和明细；`added`、`removed` 同理。只删除区块内的必填字段会校验失败，不会静默发送。

## 部署后验证

```bash
# 1. 渲染预览：只打印将要推送的内容，不发送、不推进游标
python -m src.intranet_notifier --once --dry-run

# 2. 单轮真实发送（失败退出码非 0）
python -m src.intranet_notifier --once

# 3. 看服务状态与日志
systemctl --user status kimiclaw-monitor kimiclaw-notifier
journalctl --user -u kimiclaw-notifier -f

# 4.（可选）跑测试自检（pytest 已在 requirements.txt 里，install.sh 已装）
pytest
```

## @机器人 提需求

装上机器人后可以在群里 @机器人 用自然语言提需求（改监控目标、加关注版本、调过滤规则），由 Claw 按 `skills/ff-config-assistant` 的草案协议代笔改写 config（起草 → 群内回显 → 逐字「写入」确认 → 落盘 → 校验，失败自动回滚）。

部署要求：

1. Node ≥ 22，`npm i -g openclaw`
2. 安装企微插件 `wecom-openclaw-plugin` 与 `@openclaw/kimi-provider`；kimi-claw 插件需要 Kimi Claw 订阅号环境
3. `~/.openclaw/openclaw.json`：填入同一机器人的 `channels.wecom` 凭证，`skills.load.extraDirs` 指向本仓库 `skills/`
4. 重跑 `scripts/linux/install.sh`（检测到 openclaw 会自动加装 `kimiclaw-openclaw-gateway.service`）

## @机器人 控制 program 脚本

`skills/ff-program-assistant` 让 Claw 查询、启动和停止 `program/.env` 的 `BASH` 变量中登记的脚本。新增脚本只需放入 `program/`、加入 BASH 并在 `program/README.md` 写明用途和参数，不需要修改 Skill。

```dotenv
BASH=heartbeat.sh,disk_check.sh,system_info.sh
```

本地固定命令：

```bash
python -m src.program_manager status
python -m src.program_manager start heartbeat.sh 5
python -m src.program_manager stop heartbeat.sh
```

查询遍历 BASH 并用 pgrep 检查实际进程；启动前查重，未运行时用 `bash` 启动。`src/io.py` 以 `Output` 基类共用模板操作、JSONL 日志和终端输出，`IntranetOutput`、`ProgramOutput` 分别负责内网告警和程序管理文案；`config/program-output-template.json` 定义程序管理文案，Claw 直接回复结果中的 `message`。操作日志在 `logs/program-control/YYYY-MM-DD.log`，Claw 通过 `--question` 将用户原话写入 `question`，失败请求也会留痕；脚本输出在 `logs/program-control/output/`，不维护 PID 状态文件。详见 [程序管理说明](docs/program-control.md)。

## 机器人问答日志

通知器每轮自动把企微群里的用户问题和机器人最终回答写入 `logs/chat/YYYY-MM-DD.log`，每天一个文件，有问答才生成。`config/chat-log-template.json` 控制新记录的 JSON 字段和内容，每次同步重新读取；`answerId` 必须保留用于去重，已有日志不会被改写。默认每条包含 `question`、`answer`、问答时间和消息 ID，不记录模型思考过程或工具细节。也可以手动同步：

```bash
python -m src.io
```

## 文件树

```
kimiclaw-monitor-messages/
├── src/                        # 核心代码
│   ├── intranet_filename_monitor.py   # 采集器：轮询内网页面 → diff/版本快照/错误日志
│   ├── intranet_notifier.py           # 通知器：游标消费 → 规则判定 → 调用统一输出并推送
│   ├── triage_rules.py                # 重要性规则引擎（每轮热读规则文件）
│   ├── program_manager.py             # program/ 脚本查询、启动、停止
│   ├── io.py                          # Output / IntranetOutput / ProgramOutput / ChatLogger
│   ├── bot_tool.py                    # 连接编排：借线推送 / 拉活 Claw / 失败退避
│   └── wecom_bot_client.py            # 企微机器人长连接协议层（纯传输）
├── program/                    # 通用受管 Bash 脚本及调用说明
├── skills/
│   ├── ff-config-assistant/SKILL.md   # @机器人 需求变更草案协议（可选 OpenClaw 用）
│   └── ff-program-assistant/SKILL.md  # @机器人 程序控制固定命令手册
├── config/                     # 配置（全部热读；*.example.json 为入库模板）
├── scripts/
│   ├── linux/                         # install.sh + 3 个 systemd unit 模板
│   ├── windows/                       # Windows 计划任务脚本（历史回滚保留）
│   └── poc_wecom_ws.py                # 企微长连接单文件 PoC
├── state/                      # 运行态（不入库：游标、心跳锁、草案台账、凭证）
├── logs/                       # 产物日志（diff / 版本快照 / 通知 / 程序控制 / 每日问答）
├── tests/                      # pytest 自检
├── docs/                       # 现行文档（见下）
├── wiki/                       # 调研存档（KIMICLAW 调研报告、连接独占实测等）
└── openspec/                   # 变更管理（specs/ 现行规格，changes/archive/ 历史）
```
