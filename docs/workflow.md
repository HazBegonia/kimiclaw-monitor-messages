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

Python 发现扫描或本地持久化错误时，将原始技术错误写入 `logs/intranet-error/YYYY-MM-DD.log`（JSONL）。记录包含错误阶段、异常类型、脱敏上下文、`eventId` 和最近一次成功状态是否保留。当前阶段只生成原始错误日志，不做业务重要性判断、不生成分析日志；邮件告警（见下）只按类型聚合转发，业务重要性判断与企业微信/钉钉通知后续再由 Claw skill 接入。

## 邮件告警（SMTP → 邮箱）

`run-intranet-monitor.ps1` 在单次扫描结束后自动调用 `python -m src.email_notifier`（常驻 `Start` 模式下 monitor 不会退出，邮件告警只在 cron 使用的 `Once` 模式下生效）。行为：

- **版本变动**：自上次发送以来的新 diff 日志合并为一封汇总邮件，含增删文件清单、各选中版本明细与日志路径；无新变动不发。
- **监控异常**：`logs/intranet-error/` 的新记录按 `errorType + phase` 聚合成一封邮件，写明次数与首末时间（例如 `TimeoutError（fetch_page）×34`）；无新错误不发。
- **去重与基线**：发送位置记录在 `state/notify-state.json`，已发内容不重复投递；首次运行以当前日志位置为基线，历史日志不补发。发送失败不推进游标，下一轮 cron 自动重试，且不影响监控扫描本身。

SMTP 凭据配置在 `config/smtp.local.json`（已加入 `.gitignore`，模板见 `config/smtp.local.example.json`），字段：`host` / `port` / `username` / `auth_code` / `from` / `to`。当前使用 QQ 邮箱 SMTP（`smtp.qq.com:465`）发件，授权码在 QQ 邮箱网页版"设置 → 账号 → POP3/IMAP/SMTP"处开通。配置文件缺失或字段不全时跳过发送、不影响监控。

验证链路：`python -m src.email_notifier --test` 发送一封测试邮件。注意 QQ 邮箱发往外部邮箱可能被误判垃圾邮件，若收件箱看不到请检查垃圾邮件并把发件地址加为联系人。

脚本使用固定 `declaration-key`，重复注册同名任务可复用同一声明。删除时先执行 `-Action List`，再按返回的任务 ID：

```powershell
.\scripts\register-openclaw-intranet-cron.ps1 -Action Remove -JobId <任务ID>
```

OpenClaw cron 的调度粒度适合分钟级（例如 `-Every 1m`、`-Every 5m`），不适合 5 秒级实时监控。若必须约 5 秒轮询，请改用 `python -m src.intranet_filename_monitor --interval 5` 常驻模式（并接受需要单独守护该进程）。当前最小尝试的告警出口为邮件（见上节），未接入企业微信或钉钉。
