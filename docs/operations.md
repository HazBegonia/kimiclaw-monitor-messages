# 运维手册(启动 / 停止 / 排障)

> 适用于 2026-09-22 起的 Linux systemd 部署(FF 服务器 172.16.30.97)。架构见 `architecture.md`;环境安装见 `linux-deployment.md`;采集器细节见 `intranet-file-monitor.md`。Windows 计划任务时代的操作方式已退役。

## 1. 服务组成

| 组件         | unit                                | 职责                                                                                                                               |
| ------------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| 采集器       | `kimiclaw-monitor.service`          | 每 10 秒抓内网页面 → 变化写 `logs/intranet-diff/`、版本快照(仅变化时)写 `logs/intranet-focus/<id>/`、错误写 `logs/intranet-error/` |
| 通知器       | `kimiclaw-notifier.service`         | 每 10 秒按游标消费日志 → 规则引擎判定(`config/triage-rules.json`)→ 重要则聚合一条 markdown 经 FF 长连接推企微群,推完拉活 Claw      |
| Claw gateway | `kimiclaw-openclaw-gateway.service` | `openclaw gateway run`,收上级 @FF 需求;不参与推送                                                                                  |

三服务**互不依赖**,可单独启停。均为 `Restart=always`;linger 已开启,开机自启、注销不掉。

## 2. 用 systemctl --user 启停,journalctl 看日志

```bash
# 状态 / 启停 / 重启
systemctl --user status kimiclaw-monitor kimiclaw-notifier kimiclaw-openclaw-gateway
systemctl --user stop    kimiclaw-notifier
systemctl --user start   kimiclaw-notifier
systemctl --user restart kimiclaw-openclaw-gateway

# 跟踪日志(统一走 journald,不再有 Windows 弹窗/UTF-16 问题)
journalctl --user -u kimiclaw-monitor -f
journalctl --user -u kimiclaw-notifier -f
journalctl --user -u kimiclaw-openclaw-gateway -f
```

## 3. 前台调试(先停对应 service)

```bash
# 采集器:常驻 / 单次
python -m src.intranet_filename_monitor --interval 10 --timeout 10
python -m src.intranet_filename_monitor --once

# 通知器:常驻 / 单次 / 单次预览(不发送、不推进游标)
python -m src.intranet_notifier --interval 10
python -m src.intranet_notifier --once
python -m src.intranet_notifier --once --dry-run
```

> ⚠️ 前台跑之前必须先 `systemctl --user stop` 对应服务,否则后起实例因单实例心跳锁(`state/*-resident.lock`)安静退出,看起来没启动。
> 通知器 `--once` 失败时退出码非 0(config 错误为 2,发送失败为 1),便于脚本判断。

## 4. 配置速查(全部热读生效)

| 文件                            | 内容                                       | 生效方式                                              |
| ------------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| `config/monitors.json`          | 监控目标(URL、id)                          | 下一轮扫描生效                                        |
| `config/intranet-versions.json` | 版本选择清单                               | 下一轮扫描生效(空数组=停用版本快照)                   |
| `config/triage-rules.json`      | 重要性规则(diff/error/抖动抑制/升级窗口/文件名抑制 filenamePatterns/文件名关注 filenameIncludePatterns) | 通知器热读,下一轮生效;坏文件或含未知字段自动回退 last-good 并告警 |
| `config/notifier.json`          | chatid、目录、游标文件、secrets 路径、超时 | 通知器热读,下一轮生效                                 |

变更入口两条等价:人直改;或群内 @FF 提需求,经 `skills/ff-config-assistant/SKILL.md` 草案协议(起草 → 回显 → 逐字「写入」→ 落盘 → 写后校验,失败自动回滚)由 Claw 代笔,白名单外一律拒绝。对话变更的草案台账在 `state/chat-drafts.json`,留痕在 `logs/intranet-notify/`(stage: `config-change`)。

**凭证**:`state/secrets/wecom-bot.json`(gitignored,仓库内禁止明文密钥);FF 凭证副本同时保留在全局 `~/.openclaw/openclaw.json` 作为回滚基础。

## 5. 排障顺序(按信号由近及远)

```text
1) logs/intranet-notify/YYYY-MM-DD.log   ← 发送留痕:stage=notify-send(成功)/ wecom-send + error(失败)/ config-change(对话配置变更)
2) logs/intranet-error/YYYY-MM-DD.log    ← 采集器技术错误(JSONL:phase/errorType/statePreserved/retryable)
3) journalctl --user -u <unit>           ← 进程级异常与重启记录
4) state/notify-state.json               ← 游标(diffCursor / errorCursor),发送成功才推进
```

常见问题:

- **群里收不到消息**:先 `python -m src.intranet_notifier --once --dry-run` 看渲染结果是否命中规则;再看 notify 留痕是否 `wecom-send` 报错(认证/超时/被顶)。FF 主动推送前置条件:群里须有人 @FF 发过消息;机器人被移出群再加回后需重新 @FF 并核对 `config/notifier.json` 的 chatid。
- **Claw 不回 @FF 消息**:查 `state/bot-tool-state.json` 是否有 `pendingRestore` 欠账未补;通知器每轮会自动补拉活,也可手动 `systemctl --user restart kimiclaw-openclaw-gateway`。
- **连接被顶(disconnected_event)**:FF botId 连接独占,确认没有第二处(如旧 Windows 机器)持同一凭证在线。
- **改了 config 没生效**:采集器/通知器均为下一轮热读;若改的是 `~/.openclaw/openclaw.json`,需重启 gateway 服务。

## 6. 回滚到 Windows(分钟级)

先停 Linux 侧三服务,再回本机 Windows 执行:

```powershell
Enable-ScheduledTask -TaskName KimiclawIntranetResident, KimiclawIntranetNotifier, KimiclawOpenclawGateway
Start-ScheduledTask   -TaskName KimiclawIntranetResident, KimiclawIntranetNotifier, KimiclawOpenclawGateway
```

游标两界通用,回滚无重复推送。注意任何时候只能一侧在线(botId 连接独占)。
