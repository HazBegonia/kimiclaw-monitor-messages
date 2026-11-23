# Bash 示例脚本

在 `program/.env` 注册：

```dotenv
BASH=heartbeat.sh,disk_check.sh,system_info.sh
```

## 脚本

- `system_info.sh`：输出系统信息后退出。
- `disk_check.sh [目录] [阈值]`：检查分区使用率。
- `heartbeat.sh [间隔秒数]`：持续输出心跳，默认 5 秒。

## 固定命令

```bash
# for 遍历 BASH，查询每个脚本 PID
python -m src.program_manager status

# 先查询，未运行才用 bash 启动
python -m src.program_manager start heartbeat.sh 5

# 先查询，找到 PID 才停止
python -m src.program_manager stop heartbeat.sh
```

`registered` 是注册清单，`running` 是实际运行清单。重复启动返回 `alreadyRunning: true`。

日志：

- 操作日志：`logs/program-control/YYYY-MM-DD.log`
- 脚本输出：`logs/program-control/output/`

新增脚本只需放入 `program/`、加入 BASH 并更新本说明，无需修改管理器或 Skill。
