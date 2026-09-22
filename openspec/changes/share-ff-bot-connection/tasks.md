# Tasks: share-ff-bot-connection

## 1. bot_tool 工具层

- [x] 1.1 新建 `src/bot_tool.py`：`push_markdown(text)`（经 `wecom_bot_client` 连接→发送→断开）与账本读写（`state/bot-tool-state.json`，损坏按空账本处理）
- [x] 1.2 实现踢线拉活：建连前记 `pendingRestore`，发送结束断开后调用 `openclaw config set channels.wecom.enabled` false→true（`shutil.which` 解析 openclaw.cmd，显式处理超时与返回码；gateway 不可达只留欠账不报错）
- [x] 1.3 实现 `ensure_companion_alive()`：未清偿且到期欠账 → 执行拉活；无欠账空操作
- [x] 1.4 实现发送失败退避：`sendBackoff` 5s→30s→5m 封顶，成功清零，状态持久化；退避未到期 `push_markdown` 直接报错不建连
- [x] 1.5 预留扩展位：`dump_inbox()` 空实现与多渠道注册点（注释标明）

## 2. 通知器改造

- [x] 2.1 `src/intranet_notifier.py` 推送路径改为 `bot_tool.push_markdown()`；常驻循环每轮先调 `ensure_companion_alive()`
- [x] 2.2 移除通知器内被工具层接管的直连/重试逻辑；保留游标推进语义（成功才推游标）

## 3. 测试

- [x] 3.1 新建 `tests/test_bot_tool.py`：推送全流程 mock、发送失败仍拉活、崩溃欠账补拉活、退避表推进与清零、账本损坏自愈、CLI 调用失败留欠账
- [x] 3.2 更新 `tests/test_intranet_notifier.py` 适配新调用路径；`python -m pytest tests/` 全绿

## 4. 运维接入

- [x] 4.1 用 `scripts/register-windows-scheduler.ps1` 注册 gateway 常驻任务（`openclaw gateway run`，登录触发 + 守护触发器），确认重启后存活
- [x] 4.2 恢复 `channels.wecom.enabled=true`，确认 Claw 经 FF 收 @消息正常

## 5. 踢线演练（验证 design.md 两个 Open Questions）

- [x] 5.1 Claw 持线状态下 `python -m src.intranet_notifier --once` 实发：确认 Claw 被踢→数秒内被拉活、通知器推送成功、互踢无循环
- [x] 5.2 检查热重载对 Kimi 桥的影响（日志无异常断连/续订正常）
- [x] 5.3 窗口消息实测：推送瞬间 @FF 发消息，确认服务器是否补发（结论记入 wiki）

## 6. 文档收尾

- [x] 6.1 更新 `wiki/wecom-bot-connection-exclusivity.md` 「现行决议」节为单 FF 共用 + 拉活编排
- [x] 6.2 更新 AGENTS.md 当前架构节（bot_tool 层、gateway 常驻任务、单 FF 约定）
