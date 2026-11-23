# Design

## Context

按用户确认的最简实现：`program/.env` 注册 BASH，几个函数供 Claw 调用，不维护 PID 状态文件。

## Decisions

- `registered()`：用 python-dotenv 读取 BASH，支持分隔字符串和 JSON 数组。
- `pids()`：用 `pgrep -f` 匹配 `bash ...program/<脚本名>`。
- `running()`：for 遍历注册项并调用 `pids()`。
- `status()`：返回 `registered` 和 `running`。
- `start()`：先查 PID；已运行直接返回，未运行用 `/bin/bash`、argv 参数和后台会话启动，输出写文件。
- `stop()`：先查 PID；找到才发送 TERM，最多等待 5 秒并复查。
- `write_log()`：按日写 JSONL，包含事件、脚本、用户原话、PID、结果和当前运行列表；失败请求记录 `error`。
- `src/io.py`：`Output` 基类统一提供模板操作、JSONL 日志和终端输出，`IntranetOutput` 负责内网告警，`ProgramOutput` 负责程序管理 `message`；程序文案来自 `config/program-output-template.json`，终端 stderr 和 Claw 群回复共用。
- `main()`：只暴露 `status/start/stop` 给 Claw；`--question` 接收用户请求原文并传入日志。

不引入注册 JSON、PID 状态目录、草案确认、复杂进程身份模型或常驻服务。日志不是状态来源，每次查询都重新执行 pgrep。

## Migration Plan

在 `program/.env` 配置 BASH，运行 pytest 和真实 CLI，再由测试群验证 @FF。回滚前停止相关脚本并停用新 Skill。
