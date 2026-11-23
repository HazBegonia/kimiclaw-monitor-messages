# Spec Delta

## Purpose

让 Claw 按 `.env` 中的 BASH 注册清单查询、启动和停止脚本，管理器直接检查实际进程并记录日志，不依赖额外 PID 状态文件。

## ADDED Requirements

### Requirement: BASH 环境变量注册

系统 SHALL 从 `BASH` 环境变量读取受管脚本，支持逗号或空白分隔以及 JSON 字符串数组。每项 MUST 指向 `program/` 内实际存在的 `.sh` 文件；新增脚本只需添加文件、登记 BASH 和补充调用说明，不得要求修改管理器或 Skill。

#### Scenario: 登记后出现在清单

- **WHEN** 管理员将一个新脚本加入 BASH
- **THEN** 下一次 `status` 的注册清单包含该脚本，无需重启管理器或修改代码

#### Scenario: 未注册脚本不能操作

- **WHEN** 请求启动或停止一个不在 BASH 中的脚本
- **THEN** 管理器拒绝操作，不创建进程或发送信号

### Requirement: 遍历注册项查询进程

`status` SHALL 遍历全部 BASH 注册项并直接检查 Bash 进程，返回完整注册清单及每项实际运行 PID。进程查询 MUST NOT 仅根据历史日志判断，且能识别命令行包含注册脚本入口的外部手动进程。

#### Scenario: 只返回实际运行项

- **WHEN** 注册项中一个脚本正在运行而另一个未运行
- **THEN** 注册清单包含两项，运行清单只包含实际运行项及其 PID

#### Scenario: 脚本已退出

- **WHEN** 脚本此前启动但查询时已退出
- **THEN** 它不出现在运行清单中

### Requirement: 检查后使用 bash 启动

`start` SHALL 先查询对应脚本，未运行时以 `/bin/bash` 和独立 argv 参数后台执行，stdout 与 stderr 写入输出日志；已运行时 MUST 返回已有 PID 且不重复启动。

#### Scenario: 启动未运行脚本

- **WHEN** 对未运行的注册脚本执行启动
- **THEN** 创建一个后台 Bash 进程并记录日志

#### Scenario: 重复启动

- **WHEN** 对应脚本已有运行进程时再次启动
- **THEN** 返回 `alreadyRunning` 和已有 PID，不创建新进程

### Requirement: 检查后停止

`stop` SHALL 使用与查询相同的方式寻找对应注册脚本，找到后发送停止信号并复核退出；未找到时 MUST 返回未运行且不发送信号。

#### Scenario: 停止运行脚本

- **WHEN** 对正在运行的注册脚本执行停止
- **THEN** 对应进程退出，日志记录停止结果和之后的运行清单

#### Scenario: 停止未运行脚本

- **WHEN** 对应脚本没有运行进程
- **THEN** 返回 `not_running`，不发送信号

### Requirement: 操作日志与 Claw 固定调用

系统 SHALL 将查询、启动、重复启动、停止和失败请求追加到按日 JSONL 日志，记录时间、目标、用户原话、PID、结果和当前运行清单。独立 Skill MUST 只调用固定 CLI，通过 `--question` 传递用户请求原文，通过 `status.registered` 获取可用脚本，不需要读取 `.env`，并按实际 JSON 结果回复。

#### Scenario: 查询留痕

- **WHEN** Claw 请求查询运行脚本
- **THEN** 管理器返回真实结果并追加一条包含当前运行清单和用户原话的查询日志

#### Scenario: 失败请求留痕

- **WHEN** 注册检查或命令执行失败
- **THEN** 日志记录用户原话、`result: "error"` 和错误内容

#### Scenario: 目标歧义

- **WHEN** 请求无法唯一对应注册清单中的脚本
- **THEN** Claw 根据注册清单追问，不执行程序

### Requirement: JSON 模板统一输出

系统 SHALL 从 `templates/program-output-template.json` 读取状态、启动、重复启动、停止、输出和错误模板，并在结果中提供渲染后的 `message`。终端和 Claw 群回复 MUST 共用该文案，修改模板不得要求修改管理器或 Skill。

#### Scenario: 修改模板后输出变化

- **WHEN** 管理员修改启动模板后执行启动
- **THEN** 结果 `message`、终端显示和 Claw 回复使用新模板
