# Linux 部署（2026-09-22 起，FF 服务器 172.16.30.97）

从 Windows 任务计划程序迁移到 Linux systemd user services。链路不变：采集器 → diff/错误日志 → 通知器 → bot_tool 借 FF 长连接推送 → 拉活 Claw。

## 环境

- 仓库：/home/u504/kimiclaw-monitor-messages（branch: release_kimiclaw_v1.0.0，用 tar 复制部署；GitHub 仓库为私有，服务器上 git pull 需凭据）
- Python：conda env `kimiclaw-monitor-messages`（/home/u504/anaconda3/envs/...，python 3.11，唯一第三方依赖 websocket-client）
- Node：/home/u504/node22（v22.20.0，用户态解压安装），openclaw 2026.6.35 全局装在其中
- openclaw 配置：~/.openclaw/openclaw.json（从 Windows 复制后清洗：skills extraDirs 指向服务器仓库、去掉 weixin hooks；channels.wecom 凭证同 FF）
- 插件：wecom-openclaw-plugin@2026.5.7、@openclaw/kimi-provider（CLI 安装）；kimi-claw 0.27.1（npm 没有，从 Windows ~/.openclaw/extensions/kimi-claw 整目录拷贝）
- linger 已开启（loginctl enable-linger u504），服务随开机启动、注销不掉

## 服务（systemd --user，unit 文件在 scripts/linux/，已拷到 ~/.config/systemd/user/）

- kimiclaw-monitor.service：python -m src.intranet_filename_monitor --interval 5 --timeout 10，Restart=always
- kimiclaw-notifier.service：python -m src.intranet_notifier --interval 5，PATH 含 node22/bin（bot_tool 拉活 Claw 要用 openclaw CLI）
- kimiclaw-openclaw-gateway.service：openclaw gateway run

## 常用命令（ssh FF 后执行）

    systemctl --user status kimiclaw-monitor kimiclaw-notifier kimiclaw-openclaw-gateway
    systemctl --user restart kimiclaw-openclaw-gateway
    journalctl --user -u kimiclaw-notifier -f          # 跟踪通知器
    journalctl --user -u kimiclaw-openclaw-gateway -f  # 跟踪 Claw/wecom

## 排障要点

- 不再有 Windows 弹窗/UTF-16 日志/守护触发器问题；日志统一走 journald。
- bot_tool 借线推送仍会短暂踢掉 Claw 的 wecom 连接，推完自动 config set 拉活（欠账在 state/bot-tool-state.json）。
- FF botId 连接独占：Windows 侧三个计划任务已 Disabled，不可两边同时跑。
- 回滚 Windows：本机执行 Enable-ScheduledTask + Start-ScheduledTask（KimiclawIntranetResident / KimiclawIntranetNotifier / KimiclawOpenclawGateway），并先停 Linux 侧三服务。
