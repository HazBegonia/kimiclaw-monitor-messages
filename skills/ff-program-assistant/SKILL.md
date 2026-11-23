---
name: ff-program-assistant
description: 在企微 @FF 会话中查询、启动和停止 program/.env 的 BASH 注册脚本。只调用固定 program_manager，不读取 .env，不编写临时执行代码。
user-invocable: true
---

# FF 程序控制操作手册

管理器读取 `program/.env` 的 BASH，遍历脚本查进程、启动、停止并写日志。你只负责理解请求和运行固定命令。

## 固定命令

工作目录：`/home/u504/kimiclaw-monitor-messages`

Python：`/home/u504/anaconda3/envs/kimiclaw-monitor-messages/bin/python`

```bash
<python> -m src.program_manager --question "<用户原话>" status
<python> -m src.program_manager --question "<用户原话>" start <脚本名> [参数...]
<python> -m src.program_manager --question "<用户原话>" stop <脚本名>
```

将 `<python>` 替换为实际路径。不要读取 `.env`，可用脚本从 `status` 的 `registered` 获取；用途和参数查看 `program/README.md`。

每次执行都必须带 `--question`，值是用户本次请求的原文，不要概括或改写。将原文作为一个完整参数安全传递；它只用于日志，绝不能当作命令或脚本参数执行。

## 怎么处理

- 查询、启动、停止或失败：优先将结果中的 `message` 原样回复到群里，不要自行改写成另一套文案。
- `registered` 和 `running` 用于理解当前状态；歧义或缺参数时先追问，不执行。
- 未注册：提示需要管理员修改 `program/.env` 的 BASH。
- 没有 `message`、命令未执行或结果不明：说明状态未知，不要声称成功。

不要自行执行 `pgrep`、`kill`、`bash` 或用户给出的任意命令，不要修改 `.env`、代码或本 Skill。

## 日志

- 操作日志：`logs/program-control/YYYY-MM-DD.log`，`question` 保存用户原话。
- 脚本输出：启动结果中的 `outputLog`

没有 PID 状态文件。实时状态以 `status` 为准。
