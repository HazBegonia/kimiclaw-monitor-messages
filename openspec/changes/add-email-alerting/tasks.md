# Tasks: add-email-alerting

## 1. 配置与凭据

- [x] 1.1 `.gitignore` 增加 `*.local.json` 规则，确保凭据文件不入库
- [x] 1.2 新建 `config/smtp.local.example.json` 模板（host/port/username/auth_code/from/to/channel 字段，占位值）
- [x] 1.3 用户按模板创建真实 `config/smtp.local.json`（QQ 邮箱 SMTP 授权码，收件人 26213050235@m.fudan.edu.cn）——用户手动完成

## 2. 发送器模块

- [x] 2.1 新建 `src/email_notifier.py`：SMTP_SSL 发送函数 `send(subject, body)`，RFC 2047 主题编码、纯文本 UTF-8 正文
- [x] 2.2 实现配置加载与降级：`config/smtp.local.json` 缺失/字段不全时打印提示并正常退出（exit 0）
- [x] 2.3 实现游标状态 `state/notify-state.json`：diff/focus 文件名游标 + error JSONL (日期, 字节偏移)；状态缺失时以当前最新位置为基线
- [x] 2.4 实现版本变动汇总：读取游标之后的新 diff/focus 日志，合并为一封邮件（增删清单 + 日志路径，明细超 50 条截断并注明）
- [x] 2.5 实现异常聚合：读取 error JSONL 游标之后的新记录，按 (errorType, phase) 分组计数 + 首末时间，合并为一封邮件
- [x] 2.6 发送失败处理：捕获异常、控制台输出原因、游标不推进、进程正常退出
- [x] 2.7 CLI 入口 `python -m src.email_notifier`，支持 `--test` 发送一封测试邮件验证链路

## 3. 测试

- [x] 3.1 新增 `tests/test_email_notifier.py`：聚合逻辑、游标推进/缺失基线、配置缺失降级、失败不重发语义（SMTP 用 mock）
- [x] 3.2 运行现有测试套件 `python -m pytest tests/`，确认无回归

## 4. 接入链路

- [x] 4.1 `scripts/run-intranet-monitor.ps1` 在 monitor 调用后追加 `python -m src.email_notifier`（保持 UTF-8 with BOM 编码保存）
- [x] 4.2 端到端验证：运行 `--test` 发测试邮件到收件邮箱，确认到达（必要时加白名单）

## 5. 文档

- [x] 5.1 更新 `docs/workflow.md`：邮件告警环节说明、smtp.local.json 配置方法、QQ→复旦白名单提醒
