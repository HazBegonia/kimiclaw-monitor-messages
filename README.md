# kimiclaw-monitor-messages

内网信息监控系统：轮询内网页面 → 规则过滤重要性 → 企业微信会话推送（群聊或私聊）。核心链路纯 Python、无 LLM 依赖；可选叠加 Kimi Claw（OpenClaw），直接在群里 @机器人 提需求变更。

```
【推送链路】
内网页面 ──轮询──> 采集器 ──> 本地日志（diff/版本快照/错误）
                             │
                             ▼
                          通知器 ──规则判定──> 聚合 markdown
                             │
                             ▼
              企业微信智能机器人长连接 ──> 目标会话（群聊/私聊）

【需求链路（OpenClaw）】
群里 @机器人 ──> Claw gateway ──草案协议──> 改写白名单配置
                                                      │
                                                      ▼
                                  采集器/通知器下一轮热读生效

【Bash 控制链路（OpenClaw）】
群里 @机器人 ──> Claw gateway ──> ff-program-assistant ──> program_manager
                                                            │
program/.env 的 BASH 注册清单 ───────────────────────────────┘
                                                            ▼
                                            status 查询 / start 启动 / stop 停止
                                                            │
                                                            ▼
                                                  ProgramOutput 生成回复
                                                            │
                                                            ▼
                                       logs/program-control/ 写操作和输出日志
```

## 从0开始部署

下面按**完整功能**部署：内网监控和推送、群里 @机器人 改配置、查询或控制 Bash，以及从 Kimi 网页访问这台 Claw。只部署监控和推送时，可以跳过第 2～5 步；项目核心链路不依赖 OpenClaw 或 LLM。

准备一台使用 systemd 的 Linux 机器。它需要能访问内网监控页面，并能出网访问 Kimi、OpenClaw、npm 和企业微信服务器；本机需有 `git`、`curl`、Python ≥ 3.11。所有命令都用运行服务的同一个 Linux 用户执行，不要换到 root。

### 1. 注册企业微信智能机器人

1. 打开企业微信电脑客户端，进入 **工作台 → 智能机器人**。
2. 点击 **创建**，选择 **手动创建**。填写机器人名称（例如 `FF`）和用途说明。
3. 在创建页面底部切换为 **API 模式**，连接方式选择 **长连接**。长连接只需要部署机器能访问企业微信服务器，不需要公网 IP、域名备案或可信 IP。
4. 完成创建后，保存机器人的 **BotID** 和 **Secret**。Secret 要区分大小写，不要发到群里或提交到 Git。
5. 检查机器人的 **消息** 权限。如果调用时返回 `errcode 850002`，需要机器人创建者在 **工作台 → 智能机器人** 中完成消息权限授权。
6. 准备接收告警的目标会话。群聊：把机器人加入目标群，等第 6 步的 gateway 启动后在群里 @机器人 发一条消息，再用 `openclaw sessions list` 找到群 `chatid`，并设置 `chatType: 2`。私聊：让目标用户给机器人发一条消息，从私聊回调记录用户 `userid`，并设置 `chatType: 1`。

长连接的技术说明可查看 [企业微信官方文档](https://developer.work.weixin.qq.com/document/path/101463)。

### 2. 在新机器上安装 OpenClaw

机器上不需要提前安装 Node 或 OpenClaw。执行[官方安装脚本](https://docs.openclaw.ai/install)，它会检查系统、安装受支持的 Node 和 OpenClaw：

```bash
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
```

安装结束后重新打开终端，让 `PATH` 生效，再检查：

```bash
node --version
openclaw --version
openclaw doctor
```

如果提示 `openclaw: command not found`，执行 `npm prefix -g`，把输出目录下的 `bin` 加入当前用户的 `PATH`。不要用另一台机器上的 Node 版本要求替代官方安装脚本的检查结果。

### 3. 配置 Kimi 模型

本项目当前服务器使用 Kimi Code 的 `kimi-for-coding` 作为 Claw 默认模型。新部署按下面的官方插件方式配置，不需要手工编写模型 provider JSON。

1. 确认 Kimi 会员已开通 Kimi Code 权益。
2. 按 [Kimi Code 接入说明](https://www.kimi.com/code/docs/third-party-tools/other-coding-agents.html)进入 Kimi Code 控制台，点击 **新建 API Key**。完整 Key 只显示一次，妥善保存。
3. 在部署机器上安装模型插件并启动交互式配置：

```bash
openclaw plugins install @openclaw/kimi-provider
OPENCLAW_LOCALE=zh-CN openclaw onboard --classic \
  --auth-choice kimi-code-api-key \
  --skip-daemon --skip-channels --skip-ui
```

按提示粘贴 Kimi Code API Key。Agent 使用默认的 `main`，工作目录可保持 `~/.openclaw/workspace`。这里跳过 OpenClaw 自带的 gateway 服务和渠道向导，因为第 4 步会配置企业微信，第 6 步会由本项目安装 gateway 服务。

4. 选择并验证默认模型：

```bash
openclaw models set kimi/kimi-for-coding
openclaw models status
openclaw agent --local --session-id setup-smoke-test \
  --message '只回复：KIMI_OK'
```

最后一条命令会真实调用模型，应返回 `KIMI_OK`。模型配置和 Key 由 OpenClaw 保存在当前用户的 `~/.openclaw/`，不要复制到仓库。

> 新版 OpenClaw 的模型名是 `kimi/kimi-for-coding`。本项目现有服务器使用旧版 provider ID，因此 `openclaw models status` 显示 `kimi-coding/kimi-for-coding`；两者指的是同一类 Kimi Code 模型，不要在旧服务器上强行改成新版前缀。以本机 `openclaw models list` 和 `models status` 的结果为准。详见 [OpenClaw 的 Kimi 模型文档](https://docs.openclaw.ai/providers/moonshot)。

### 4. 安装企业微信插件并接入机器人

使用[企业微信官方 OpenClaw 插件](https://github.com/WecomTeam/wecom-openclaw-plugin)，不要用同名社区插件替代：

```bash
npx -y @wecom/wecom-openclaw-cli install
```

安装向导会询问 **Bot ID** 和 **Secret**，填第 1 步创建的同一个机器人。连接模式使用默认的 `websocket`，然后确认渠道已启用：

```bash
openclaw config set channels.wecom.connectionMode websocket
openclaw config set channels.wecom.enabled true
npx -y @wecom/wecom-openclaw-cli doctor
openclaw plugins list
```

插件列表中应看到 `@wecom/wecom-openclaw-plugin` 和 `@openclaw/kimi-provider`。此时共有三类插件，用途不要混淆：

| 插件                           | 用途                                  | 安装来源                    |
| ------------------------------ | ------------------------------------- | --------------------------- |
| `@openclaw/kimi-provider`      | 给 Claw 提供 Kimi 模型和 API Key 认证 | 第 3 步的 OpenClaw 命令     |
| `@wecom/wecom-openclaw-plugin` | 接收和回复企业微信消息                | 第 4 步的企微官方安装向导   |
| `kimi-claw`                    | 把本地 OpenClaw 关联到 Kimi 账号      | 第 5 步的 Kimi 网页专属命令 |

### 5. 关联已有 OpenClaw 到 Kimi Claw

这一步不是新建云端 Claw，而是把刚装好的本地 OpenClaw 绑定到 Kimi 账号：

1. 用开通了 Kimi 会员的账号登录 [kimi.com/bot](https://www.kimi.com/bot)。
2. 选择 **关联已有 OpenClaw / Link Existing OpenClaw**，不要点 **Create**。
3. 网页会生成一条包含本次关联 token 的插件安装命令。复制网页给出的**完整命令**，在这台 Linux 机器上、以运行 OpenClaw 的同一用户执行。token 不要发到群里或写入仓库。
4. 安装完成后检查：

```bash
openclaw plugins info kimi-claw
```

状态应为 `loaded`。Kimi 网页的 Claw 列表中应出现这台 OpenClaw。关联方法和托管云 Claw 的区别见 [Kimi Claw 官方概览](https://www.kimi.ai/help/kimi-claw/overview)。

`kimi-claw` 必须使用 Kimi 网页为当前账号生成的安装方式，不要执行 `npm install -g kimi-claw`，也不要从其他服务器复制插件目录代替关联。

### 6. 部署本项目并加载 Skills

```bash
# 1. 获取代码
git clone <仓库地址>
cd kimiclaw-monitor-messages   # 或直接解压 tar 包后进入项目目录

# 2. 让 main agent 加载本项目的配置助手和程序控制手册
#    全新安装直接执行；若已有其他 extraDirs，请合并数组，不要覆盖旧值
openclaw config set skills.load.extraDirs "[\"$PWD/skills\"]"
openclaw config get skills.load.extraDirs

# 3. 准备 Python 环境（二选一）
#    a. conda（推荐，与 FF 服务器一致）：
conda create -y -n kimiclaw-monitor-messages python=3.11
#    b. 没有 conda 就跳过这步，install.sh 会在仓库下自动建 .venv

# 4. 安装依赖、生成配置、安装 systemd unit，但先不启动
scripts/linux/install.sh --no-start
#    用了 conda 时指定解释器：
#    scripts/linux/install.sh --no-start --python "$(conda run -n kimiclaw-monitor-messages python -c 'import sys; print(sys.executable)')"
#    检测到 openclaw 时会同时安装 kimiclaw-openclaw-gateway.service

# 5. 填写与 OpenClaw 企业微信渠道相同的机器人凭证
vim state/secrets/wecom-bot.json
#    { "botId": "你的BotID", "secret": "你的Secret" }
```

按实际环境编辑 `src/.env` 和 `config/` 下的 JSON 文件，尤其是 `config/monitors.json` 的内网 URL，以及 `config/notifier.json` 的目标会话 `chatid` 和 `chatType`，详见下节「配置说明」。群聊目标设置 `chatType: 2`，如果还没有群 `chatid`，先启动一次 gateway，在目标群 @机器人 后执行 `openclaw sessions list` 获取；私聊目标设置 `chatType: 1`，`chatid` 填已在机器人私聊中发过消息的用户 `userid`。

启动完整服务：

```bash
systemctl --user restart kimiclaw-monitor kimiclaw-notifier kimiclaw-openclaw-gateway
systemctl --user status kimiclaw-monitor kimiclaw-notifier kimiclaw-openclaw-gateway
```

需要开机自启、注销后仍运行：

```bash
loginctl enable-linger <用户名>
```

注意事项：

- **同一 botId 连接独占**：一个机器人同时只能一处在线。不要用同一个机器人凭证部署第二套。项目通知器推送时会短暂借用连接，随后自动恢复 Claw。
- 机器人被移出群再加回后，需要重新 @机器人 并核对群 chatid；私聊推送失效时，让目标用户重新在私聊中给机器人发消息并核对 userid。
- OpenClaw 的模型 Key、关联 token 和企微 Secret 都属于全局运行环境或凭证文件，不要写进项目配置、日志或 Git。

## 配置说明

常量值放在 `src/.env`，监控目标、机器人、通知规则和定时配置放在 `config/*.json`：

| 文件                            | 要改什么                                                                                 | 说明                                                                                      |
| ------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `src/.env`                      | `DEFAULT_URL`、`DEFAULT_INTERVAL`、`DEFAULT_TIMEOUT`、`TIME_ZONE`、日志/锁路径、渲染限制 | 模块加载时读取，修改后重启对应服务                                                        |
| `config/monitors.json`          | `url` 改成实际内网页面地址                                                               | 监控目标清单；`profile` 描述页面结构（如只认 `.csv` 链接），多目标可加多项                |
| `config/notifier.json`          | `chatid`、`chatType`、`sourceUrl`、`templateFile`                                        | 通知器 JSON 配置；`chatType: 1` 为私聊、`2` 为群聊，缺省按群聊处理                        |
| `config/intranet-versions.json` | `match` 填关注的版本号/字段                                                              | 命中字段的文件集合变化时额外记版本快照；空数组 `[]` = 停用该功能                          |
| `config/triage-rules.json`      | 按需调整                                                                                 | 重要性规则：新增/删除文件默认推、错误推送类型、文件名 suppress/include 过滤。默认值即可跑 |

代码通过 `python-dotenv` 直接读取 `src/.env`，再用 `os.getenv()` 取得常量；系统环境变量优先。机器人凭证仍只放在 `state/secrets/wecom-bot.json`，不放进 `.env`。

### IO 输出模板

所有输出模板单独放在 `templates/`，不与业务和运行配置混放：

| 文件                                     | 控制内容                                     |
| ---------------------------------------- | -------------------------------------------- |
| `templates/notify-template.json`         | 内网告警标题、来源、区块、错误摘要和截断提示 |
| `templates/program-output-template.json` | 脚本状态、启动、停止、重复启动和错误回复     |
| `templates/chat-log-template.json`       | 每日问答日志的新记录字段和内容               |

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
systemctl --user status kimiclaw-monitor kimiclaw-notifier kimiclaw-openclaw-gateway
journalctl --user -u kimiclaw-notifier -f
journalctl --user -u kimiclaw-openclaw-gateway -f

# 4. 检查 Claw 模型、插件和企微会话
openclaw models status
openclaw plugins list
openclaw sessions list

# 5.（可选）跑测试自检（pytest 已在 requirements.txt 里，install.sh 已装）
pytest
```

完整功能还要在群里做一次真实验收：@机器人 询问「当前监控哪些 URL」，应返回 `config/monitors.json` 的实际内容；再询问「查询运行脚本」，应返回 `program/.env` 中登记脚本的真实状态。配置变更类请求必须先回显草案，只有逐字回复「写入」才允许落盘。Kimi 网页侧也应能打开已关联的 OpenClaw 并正常对话。

## @机器人 提需求

装上机器人后可以在群里 @机器人 用自然语言提需求（改监控目标、加关注版本、调过滤规则），由 Claw 按 `skills/ff-config-assistant` 的草案协议代笔改写白名单配置（起草 → 群内回显 → 逐字「写入」确认 → 落盘 → 校验，失败自动回滚）。

首次部署按上文「从0开始部署」完成模型、企业微信插件、Kimi Claw 关联和 Skills 加载。配置修改只涉及白名单文件，不需要改采集器或通知器代码。

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

查询遍历 BASH 并用 pgrep 检查实际进程；启动前查重，未运行时用 `bash` 启动。`src/io.py` 以 `Output` 基类共用模板操作、JSONL 日志和终端输出，`IntranetOutput`、`ProgramOutput` 分别负责内网告警和程序管理文案；`templates/program-output-template.json` 定义程序管理文案，Claw 直接回复结果中的 `message`。操作日志在 `logs/program-control/YYYY-MM-DD.log`，Claw 通过 `--question` 将用户原话写入 `question`，失败请求也会留痕；脚本输出在 `logs/program-control/output/`，不维护 PID 状态文件。详见 [程序管理说明](docs/program-control.md)。

## 机器人问答日志

通知器每轮自动把企微群里的用户问题和机器人最终回答写入 `logs/chat/YYYY-MM-DD.log`，每天一个文件，有问答才生成。`templates/chat-log-template.json` 控制新记录的 JSON 字段和内容，每次同步重新读取；`answerId` 必须保留用于去重，已有日志不会被改写。默认每条包含 `question`、`answer`、问答时间和消息 ID，不记录模型思考过程或工具细节。也可以手动同步：

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
│   └── wecom_bot_client.py            # 企微长连接基类 + 群聊/私聊客户端与目标工厂
├── program/                    # 通用受管 Bash 脚本及调用说明
├── skills/
│   ├── ff-config-assistant/SKILL.md   # @机器人 需求变更草案协议（可选 OpenClaw 用）
│   └── ff-program-assistant/SKILL.md  # @机器人 程序控制固定命令手册
├── config/                     # 监控、机器人、规则和定时配置
├── templates/                  # IO 输出模板（*.example.json 为入库示例）
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
