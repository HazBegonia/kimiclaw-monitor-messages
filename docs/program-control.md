# BASH 注册脚本管理

在 `program/.env` 的 BASH 中登记脚本，例如：

```dotenv
BASH=heartbeat.sh,disk_check.sh,system_info.sh
```

支持逗号或空白分隔，也支持 JSON 字符串数组。脚本必须实际存在于 `program/`。

## 查询

```bash
python -m src.program_manager status
```

管理器 for 遍历 BASH，用 `pgrep` 查每个脚本是否运行：

- `registered`：全部注册脚本。
- `running`：实际运行脚本及 PID。

查询结果同时写入日志。

## 启动

```bash
python -m src.program_manager start heartbeat.sh 5
```

先用同一个 `pgrep` 函数查询：

- 已运行：返回 `alreadyRunning: true`，不重复启动。
- 未运行：用 `/bin/bash program/脚本名` 后台启动，参数原样传递，不经过 shell 拼接。

脚本 stdout 和 stderr 写到启动结果给出的 `outputLog`。启动后管理器等待 0.1 秒，把启动信息和当前已有的输出（最多 2000 字符）打印到终端 stderr；JSON 结果仍写 stdout 供 Claw 解析。一次性脚本可能很快退出，以之后的 `status` 为准。

## 停止

```bash
python -m src.program_manager stop heartbeat.sh
```

先查询对应 PID：

- 未运行：返回 `not_running`，不发送信号。
- 已运行：向 PID 发送 `TERM`，等待最多 5 秒并返回是否停止。

## 输出模板

`templates/program-output-template.json` 定义查询、启动、重复启动、停止、未运行、停止超时、脚本输出和错误文案。`src/io.py` 的 `ProgramOutput` 每次操作重新读取模板，用 `{{变量}}` 填充内容，并在 JSON 结果中增加 `message`。

共用的 `Output` 基类负责终端输出：stderr 打印这个 `message`，stdout 保留完整 JSON；Claw 将 `message` 原样回复到群里。因此修改模板即可同时调整终端和企微群的文案，不需要修改 Python 或 Skill。脚本原始输出仍保存在 `outputLog`。

## 日志

- `logs/program-control/YYYY-MM-DD.log`：查询、启动、重复启动、停止和失败请求，每条包含当前运行列表；Claw 通过 `--question` 传入用户原话，保存在 `question` 字段。
- `logs/program-control/output/`：脚本自身输出。

不维护 PID 状态文件。

## 新增脚本

放入 `program/`，加入 `program/.env` 的 BASH，并在 `program/README.md` 写明用途和参数。管理器和 Skill 不用修改。
