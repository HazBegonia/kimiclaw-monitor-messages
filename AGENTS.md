# 目前现状

```text
【推送链路】
内网页面 ──> 采集器 ──> 本地日志 ──> 通知器 ──> 企业微信群

【监控需求链路】
群里 @机器人 ──> Claw gateway ──草案协议──> config/*.json

【程序控制链路】
program/.env 的 BASH 注册清单
        │
群里 @机器人 ──> ff-program-assistant ──> program_manager
                                               ├─> for 遍历 BASH，用 pgrep 查询
                                               ├─> 未运行才用 bash 启动
                                               ├─> 找到 PID 才停止
                                               └─> 写操作和脚本输出日志
```

# 通用程序控制

`program/` 放置脚本，`program/.env` 的 BASH 登记受管脚本。Claw 只调用 `src/program_manager.py` 的 `status/start/stop`。

- 查询：for 遍历 BASH，逐个用 pgrep 查 PID。
- 启动：先查，未运行才用 bash 后台启动，已运行不重复启动。
- 停止：先查，找到 PID 才发送 TERM，未运行不发送信号。
- 输出：`src/io.py` 的 `Output` 基类统一处理 JSONL 日志、终端输出和共用模板操作，`IntranetOutput` 负责内网告警，`ProgramOutput` 负责程序管理文案；`config/program-output-template.json` 定义程序文案，结果中的 `message` 同时用于终端显示和 Claw 群回复。
- 日志：操作日志在 `logs/program-control/YYYY-MM-DD.log`，Claw 通过 `--question` 传入用户原话并写入 `question`，失败请求也记录；脚本输出在 `logs/program-control/output/`。

不维护 PID 状态文件，不使用草案或确认指令。新增脚本只需放入 `program/`、登记 BASH 并更新 `program/README.md`，无需修改管理器或 Skill。Claw 从 `status.registered` 获取清单，不读取 `.env`。

# Claw 问答日志

`src/io.py` 的 `ChatLogger` 从 `~/.openclaw/agents/main/sessions/` 提取企微用户问题和机器人最终文本回答，按 `config/chat-log-template.json` 渲染后写 `logs/chat/YYYY-MM-DD.log`。模板每次同步热读，仅影响新记录，必须保留 `answerId` 用于去重；忽略思考过程与工具细节，未回答的问题暂不写。通知器每轮自动同步，也可运行 `python -m src.io`；dry-run 不同步。
