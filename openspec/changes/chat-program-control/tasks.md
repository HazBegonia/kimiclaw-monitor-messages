# Tasks

## 1. 几个函数完成管理

- [x] 1.1 从 `program/.env` 读取 BASH，for 遍历注册项并用 pgrep 查询；测试注册清单、实际运行清单和未注册拒绝。
- [x] 1.2 用少量函数实现启动前查重、bash 后台启动、停止前查询、TERM 和日志，并在 `docs/program-control.md` 记录固定命令。

## 2. Claw 调用

- [x] 2.1 更新独立 Skill，通过 `status.registered` 获取脚本，调用固定 `status/start/stop`，不读取 `.env` 或生成其他执行代码。
- [x] 2.2 同步 README、部署运维文档、`program/README.md`、AGENTS 和 OpenSpec，删除旧状态文件与复杂实现说明。
- [x] 2.3 新增 `config/program-output-template.json`，为状态、启动、重复启动、停止、输出和错误生成统一 `message`；终端与 Claw 共用，并测试自定义模板生效。

## 3. 验收

- [x] 3.1 运行完整 pytest 与本次文件的差异检查。
- [x] 3.2 使用实际 `program/.env` 验证 CLI 查询，并通过临时脚本验证启动、重复启动、停止和输出日志。
- [ ] 3.3 在测试企微群实际发送 @FF 查询、启动、重复启动、停止、歧义和未注册请求；无法操作时保留未验收。
- [x] 3.4 清理临时进程、脚本、日志和缓存，不修改既有 heartbeat 进程。
