## MODIFIED Requirements

### Requirement: 扫描频率纳入需求管理

「采集需求」机器可读块 MUST 支持 `scanIntervalSeconds` 字段（缺省视为 5 秒，取值范围 2–3600）；需求激活后，常驻扫描进程的轮询间隔 MUST 与已激活需求的该字段一致。

#### Scenario: 缺省频率

- **WHEN** 「采集需求」块未声明 `scanIntervalSeconds`
- **THEN** 常驻扫描进程按 5 秒间隔轮询

#### Scenario: 修改频率经确认生效

- **WHEN** 人将 `scanIntervalSeconds` 改为 30 并经 @FF 确认激活
- **THEN** 常驻守护任务被重建或常驻进程被重启，轮询间隔更新为 30 秒

#### Scenario: 旧字段不再生效

- **WHEN** 「采集需求」块仍声明旧字段 `scanIntervalMinutes`
- **THEN** 该字段被忽略，轮询间隔按 `scanIntervalSeconds`（或缺省 5 秒）执行
