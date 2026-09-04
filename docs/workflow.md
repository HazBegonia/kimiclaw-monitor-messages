# 单一 OpenClaw 入口（内网 Web 最小尝试）

只需启动一个 OpenClaw gateway。由 OpenClaw cron 按配置文件中的间隔调用 Python **单次扫描**，不再另行启动 Windows 任务计划或 Python 常驻进程：

调度配置在 `config/openclaw-intranet-cron.json`，修改 `every` 即可调整 OpenClaw 调用频率；`scanIntervalSeconds` 和 `timeoutSeconds` 控制 Python 参数。

项目内 PowerShell 脚本已统一保存为 **UTF-8 with BOM**，兼容 Windows PowerShell 5.1。若用编辑器重新保存脚本，请保持该编码格式。

```powershell
# 在项目根目录执行；频率读取 config/openclaw-intranet-cron.json
.\scripts\register-openclaw-intranet-cron.ps1

# 查看已注册任务（包含禁用任务）
.\scripts\register-openclaw-intranet-cron.ps1 -Action List
```

任务实际执行的命令等价于：

```powershell
.\scripts\run-intranet-monitor.ps1 -Mode Once -Interval 5 -Timeout 10
```

Python 默认读取 `config/intranet-versions.json`。该文件中的 `selectedVersions` 决定哪些版本生成全量快照；例如将 `103300110002` 替换或追加为公司实际选择的版本。快照写入 `logs/intranet-focus/<version-id>/`，通用新增/删除变化仍写入 `logs/intranet-diff/`。

脚本使用固定 `declaration-key`，重复注册同名任务可复用同一声明。删除时先执行 `-Action List`，再按返回的任务 ID：

```powershell
.\scripts\register-openclaw-intranet-cron.ps1 -Action Remove -JobId <任务ID>
```

OpenClaw cron 的调度粒度适合分钟级（例如 `-Every 1m`、`-Every 5m`），不适合 5 秒级实时监控。若必须约 5 秒轮询，请改用 `python -m src.intranet_filename_monitor --interval 5` 常驻模式（并接受需要单独守护该进程）。当前最小尝试只写本地日志，未接入企业微信或钉钉。
