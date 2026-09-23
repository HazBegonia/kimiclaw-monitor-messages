# 内网监控系统 启动 / 停止 / 排障手册

> 适用于 2026-09-18 起的 py 通知器架构（OpenClaw 已退役，全链路 0 token）。
> 架构与背景见 `AGENTS.md`「当前架构：py 通知器」节；采集器细节见 `docs/intranet-file-monitor.md`。

## 1. 系统组成

| 组件 | 计划任务 | 进程 | 职责 |
|---|---|---|---|
| 采集器 | `KimiclawIntranetResident` | `python -m src.intranet_filename_monitor --interval 5 --timeout 10` | 每 5 秒抓内网页面 → 变化写 `logs/intranet-diff/`、版本快照（仅变化时）写 `logs/intranet-focus/<id>/`、错误写 `logs/intranet-error/` |
| 通知器 | `KimiclawIntranetNotifier` | `python -m src.intranet_notifier --interval 5` | 每 5 秒按游标消费日志 → 规则引擎判定（`config/triage-rules.json`）→ 重要则聚合一条 markdown 经 FF 长连接推企微群 |

两个任务**互不依赖**，可单独启停。均无 LLM、无 openclaw、0 token。

## 2. 生命周期（默认行为）

- **登录触发**：你登录 Windows 后任务自动拉起；**注销后不跑**（与旧 gateway 同生命周期），锁屏（Win+L）照跑。重启电脑后需登录一次。
- **守护触发器**（曾叫"看门狗"）：每 1 分钟自动检查一次的时间触发器兜底（任务计划程序允许的最小间隔）——runner 进程意外死亡时在下一个周期自动拉起（`IgnoreNew` 保证运行中不重复）。简单说：程序死了自动复活。
- **崩溃自愈**：Python 子进程异常退出后，runner 约 11 秒（间隔×2+1）自动重启。
- **单实例**：进程级心跳锁 `state/monitor-resident.lock` / `state/notifier-resident.lock`，后起者检测到活锁会**安静退出**（exit 0），锁陈旧可被接管。

## 3. 日常手动控制（推荐路径）

注册/控制统一走 `scripts\register-windows-scheduler.ps1`：

```powershell
# 启动采集器 / 通知器
.\scripts\register-windows-scheduler.ps1 -Action Run -TaskName KimiclawIntranetResident
.\scripts\register-windows-scheduler.ps1 -Action Run -TaskName KimiclawIntranetNotifier

# 停止（Stop 会停任务实例；若 Python 子进程仍残留，需再停对应进程）
.\scripts\register-windows-scheduler.ps1 -Action Stop -TaskName KimiclawIntranetResident
.\scripts\register-windows-scheduler.ps1 -Action Stop -TaskName KimiclawIntranetNotifier

# 查看状态
Get-ScheduledTask -TaskName 'Kimiclaw*' | Select TaskName, State
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*intranet*' } |
  Select ProcessId, CommandLine
```

## 4. 完全手动、前台运行（排障 / 实验）

```powershell
# 采集器：常驻 / 单次（--once）
python -m src.intranet_filename_monitor --interval 5 --timeout 10
python -m src.intranet_filename_monitor --once

# 通知器：常驻 / 单次 / 单次预览（不发送、不推进游标）
python -m src.intranet_notifier --interval 5
python -m src.intranet_notifier --once
python -m src.intranet_notifier --once --dry-run
```

> ⚠️ 前台跑之前**必须先 `-Action Stop` 对应计划任务**（或用 Ctrl+C 退出当前前台进程），否则后起的实例因单实例锁安静退出，看起来没启动。
> `--once` 失败时退出码非 0（config 错误为 2，发送失败为 1），便于脚本判断。

## 5. 配置速查（全部人工直改即生效）

| 文件 | 内容 | 生效方式 |
|---|---|---|
| `config/monitors.json` | 监控目标（URL、id） | 下一轮扫描生效 |
| `config/intranet-versions.json` | 版本选择清单 | 下一轮扫描生效（空数组=停用版本快照）|
| `config/triage-rules.json` | 重要性规则（diff/error/抖动抑制/升级窗口）| 通知器热读，下一轮生效，坏文件自动回退 last-good 并告警 |
| `config/notifier.json` | chatid、目录、游标文件、secrets 路径、超时 | 通知器热读，下一轮生效 |

**凭证**：`state/secrets/`（gitignored，仓库内禁止明文密钥）；FF Bot ID/Secret 副本同时保留在全局 `~/.openclaw/openclaw.json`（用户决定暂存，勿与状态文件混淆）。

## 6. 排障顺序（按信号由近及远）

```text
1) logs/intranet-notify/YYYY-MM-DD.log   ← 发送留痕：stage=notify-send(成功) / wecom-send + error(失败)
2) logs/intranet-error/YYYY-MM-DD.log    ← 采集器技术错误（JSONL：phase/errorType/statePreserved/retryable）
3) logs/intranet-scan/YYYY-MM-DD.log     ← 采集器每轮 stdin 输出 + runner 重启记录
3) state/notify-state.json               ← 游标（diffCursor / errorCursor），发送成功才推进
```

常见问题：

- **群里收不到消息**：先 `python -m src.intranet_notifier --once --dry-run` 看渲染结果是否重要；再看 notify 留痕是否 `wecom-send` 报错（认证/超时/被顶）。FF 被动推送前置条件：群里须有人 @FF 发过消息；机器人被移出群再加回后需重新 @FF 并核对 chatid。
- **通知器进程在但没日志**：9 成是单实例锁——第二次启动安静退出了，用 `-Action Run` 而非直接 python。
- **任务 Running 但 python 已死**：测 1 分钟（守护触发器周期），拉起；仍不拉起查 `logs/intranet-scan/` 的 `=== runner fatal ===` 段。
- **回滚旧链路（分钟级）**：停两个通知任务暂停 → 用 `state/backup-triage-message-2026-09-18.txt` 恢复 `config/triage-message.txt` → 起 openclaw gateway。游标两界通用，回滚无重复推送（详见 AGENTS.md）。

## 7. 当前运行状态（2026-09-18 记录）

- 采集器 PID、通知器 PID 见第 3 节命令输出；页面 `http://172.16.30.20:8011/` 应返回 HTTP 200。
- 版本快照堆积：新策略（仅变化时写、含改前/改后全量清单）已上线并验证稳定（20 秒采样文件数不变）。