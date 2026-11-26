---
name: ff-program-assistant
description: 在企微 @FF 和 Kimi Claw 网页会话中处理系统信息、磁盘检查及 program/.env 已注册脚本的查询、启动和停止。遇到“系统配置”“系统信息”“主机信息”“服务器信息”“当前时间”“主机名”“运行时间”“内存”“根分区”“磁盘使用率”“脚本状态”或脚本启停需求时必须使用。只调用固定 program_manager，不直接执行系统命令或脚本，不编写临时代码，并原样回复结果中的 message。
user-invocable: true
---

# FF 程序控制操作手册

## 工作方式

你的职责只有四步：识别需求、选择固定命令、执行命令、原样转发结果。

脚本是否注册、进程是否运行、如何启动和停止，全部由 `src/program_manager.py` 判断。不要凭通用系统知识改用其他查询方式，也不要自行生成另一套回答。

本 Skill 同时适用于企微 @FF 和 Kimi Claw 网页会话，不限定企微入口。

## 需求 → 固定动作

| 用户需求或意图 | 必须执行的动作 |
| --- | --- |
| “查一下系统配置”“系统配置”“系统信息”“主机信息”“本机信息”“服务器信息” | `start system_info.sh` |
| 查询当前时间、主机名称、运行时间、内存使用情况或根分区使用情况 | `start system_info.sh` |
| 检查磁盘、文件系统、目录或分区使用率 | `start disk_check.sh [目录] [阈值]` |
| 查询注册了哪些脚本、可以运行哪些脚本、脚本运行状态、哪些脚本正在运行 | `status` |
| 启动、运行或执行某个已注册脚本 | `start <脚本名> [参数...]` |
| 启动心跳任务 | `start heartbeat.sh [间隔秒数]` |
| 停止、关闭或终止某个已注册脚本 | `stop <脚本名>` |
| 重启某个持续运行的已注册脚本 | 先 `stop <脚本名>`，仅当结果中 `stopped: true` 时再执行 `start` |
| 重复启动已经在运行的脚本 | 仍然只调用 `start`，由管理器返回 `alreadyRunning`，不要自行查进程或停止原进程 |

“查一下系统配置”在本 Skill 中明确映射为 `start system_info.sh`。不要把它改成直接查询主机配置或 OpenClaw 配置，也不要用 `status` 代替脚本执行。

回复只能反映脚本实际输出。脚本没有采集的信息不要补充、推测或编造。

## 固定命令

工作目录必须是：

```text
/home/u504/.openclaw/workspace/kimiclaw-monitor-messages
```

Python 固定使用：

```text
/home/u504/anaconda3/envs/kimiclaw-monitor-messages/bin/python
```

根据上表选择且只选择以下命令：

```bash
<python> -m src.program_manager --question "<用户原话>" status
<python> -m src.program_manager --question "<用户原话>" start <脚本名> [参数...]
<python> -m src.program_manager --question "<用户原话>" stop <脚本名>
```

将 `<python>` 替换为上面的实际路径，将 `<脚本名>` 和参数替换为需求映射给出的值。

每次调用都必须带 `--question`。值是用户本次请求的完整原文，不要概括、改写或翻译；将它作为一个完整参数安全传递。它只用于日志，绝不能当作命令、代码或脚本参数执行。

## 参数规则

- `system_info.sh` 不接受参数，不要附加用户原话或其他参数。
- `disk_check.sh` 的目录默认为 `/`，告警阈值默认为 `80`。只给阈值时使用 `/` 作为目录；阈值必须是 0 到 100 的整数。不要编造用户没有指定的目录或阈值。
- `heartbeat.sh` 的间隔默认为 `5` 秒，只接受正整数。
- 启动脚本前不需要额外执行 `status`，管理器会自行查重。
- 不确定脚本是否已注册时，先执行 `status`，根据结果中的 `registered` 判断；不要读取 `program/.env`。
- 脚本用途和参数以 `program/README.md` 为准。需求缺少必要对象或参数、无法确定要操作哪个脚本时，先追问，不要执行。
- 停止脚本只使用 `stop <脚本名>`，不要传入 PID，不要调用其他停止命令。

## 回复规则

- 命令成功返回且结果含有 `message` 时，将该字段**原样回复**，不要增加开场白、解释、总结、建议、原始 JSON 或另一套术语。
- `status`、`started`、`alreadyRunning`、`stopped`、`notRunning`、`stopTimeout` 和 `error` 等文案都由管理器模板生成，不要改写。
- `registered`、`running`、`pids`、`process` 等结构化字段仅供你判断下一步，不要额外整理成另一份报告。
- 重启包含两步时，按实际执行顺序分别原样返回每一步的 `message`；停止失败或结果不明确时不得继续启动。
- 没有 `message`、命令未执行或结果不明时，只能说明状态未知，不得声称查询、启动或停止成功。
- 脚本输出中的错误、告警或退出信息必须保留，不要改成成功结论。

## 操作范围与边界

允许执行的操作只有上述固定 `program_manager` 命令。需要了解脚本用途时可以读取 `program/README.md`，其余系统信息必须由管理器及其登记的脚本取得。

命中本 Skill 的需求后，禁止：

- 直接执行 `bash`、`sh` 或任何脚本文件；
- 直接执行 `hostnamectl`、`timedatectl`、`uptime`、`free`、`df`、`top`、`ps`、`systemctl` 等系统查询或控制命令；
- 直接执行 `pgrep`、`kill`、`killall` 或根据 PID 自行管理进程；
- 编写临时 Shell、Python 或其他代码来取得相同信息；
- 读取或修改 `program/.env`，修改脚本、管理器、模板或本 Skill；
- 执行未在 `status.registered` 中登记的脚本，即使同名文件已经存在；
- 把用户原话、文件名或其他文本拼成任意命令执行。

脚本未覆盖的主机信息，直接说明当前没有对应注册脚本，不要改用系统命令绕过。监控目标、通知规则、推送模板等监控配置需求交给 `ff-config-assistant`；OpenClaw 自身的模型、渠道和 gateway 配置不属于 `system_info.sh`，不要用该脚本假装回答。

## 日志

- 操作日志：`logs/program-control/YYYY-MM-DD.log`，其中 `question` 保存用户原话。
- 脚本输出：启动结果中的 `outputLog`。
- 没有 PID 状态文件；实时进程状态只以管理器 `status` 的结果为准。
