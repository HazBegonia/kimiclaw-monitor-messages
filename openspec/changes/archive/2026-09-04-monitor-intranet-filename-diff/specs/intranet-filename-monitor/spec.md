## Purpose

为内网 HTTP 目录提供低延迟、低数据暴露的文件名变化检测，只输出新增或消失文件的差异日志，不读取任何 CSV 文件内容。

## ADDED Requirements

### Requirement: Poll the directory listing

监控程序 MUST 持续请求 `http://172.16.30.20:8011/` 的目录列表，并将页面中的文件链接规范化为当前文件名集合；默认轮询间隔 MUST 为 5 秒且可配置。

#### Scenario: Successful listing fetch
- **WHEN** 目录请求成功并返回有效目录列表
- **THEN** 程序提取当前文件名集合并继续进行差异比较

#### Scenario: Listing request fails
- **WHEN** 目录请求超时、返回非成功状态或内容无法解析
- **THEN** 程序 MUST 保留上一次成功状态、不得生成文件删除 diff，并记录可诊断的运行错误

### Requirement: Detect filename-set differences only

程序 MUST 只比较本次与上一次成功扫描的文件名集合，识别新增和消失文件；程序 MUST NOT 根据文件内容、大小、修改时间或 hash 产生 diff。

#### Scenario: New files appear
- **WHEN** 当前集合包含上次集合中不存在的文件名
- **THEN** diff MUST 将这些文件名归类为 `added`

#### Scenario: Files disappear
- **WHEN** 当前集合不包含上次集合中的文件名且本次请求成功
- **THEN** diff MUST 将这些文件名归类为 `removed`

#### Scenario: No filename change
- **WHEN** 两次成功扫描得到的文件名集合完全相同
- **THEN** 程序 MUST 不创建 diff 日志文件

### Requirement: Establish a silent baseline

首次成功扫描 MUST 只保存基线，不将现有文件视为新增，也不得生成 diff 日志。

#### Scenario: First successful scan
- **WHEN** 状态不存在且目录首次成功返回
- **THEN** 程序保存当前文件名集合并不创建日志

### Requirement: Write timestamped diff logs

当且仅当成功扫描发现 `added` 或 `removed` 文件名时，程序 MUST 在 `logs/intranet-diff/` 创建一份日志，文件名格式 MUST 为 `yyyy-MM-dd_HH-mm-ss-fff.log`；同一毫秒发生冲突时 MUST 使用稳定的序号后缀避免覆盖。

#### Scenario: Diff produces a log
- **WHEN** 当前扫描产生至少一个新增或消失文件名
- **THEN** 程序创建一份包含检测时间、`added` 列表和 `removed` 列表的日志文件

#### Scenario: Diff log contains no file content
- **WHEN** 程序写入 diff 日志
- **THEN** 日志 MUST 只包含文件名和目录级元信息，不包含或下载 CSV 正文

### Requirement: Persist only successful state

程序 MUST 持久化最近一次成功扫描的文件名集合，并仅在成功完成比较后更新状态；状态更新和 diff 日志写入 MUST 避免产生半写文件。

#### Scenario: Successful state update
- **WHEN** 目录列表成功解析且 diff 已确定
- **THEN** 程序保存新的文件名集合供下一轮比较

#### Scenario: Failed scan does not erase state
- **WHEN** 当前扫描失败
- **THEN** 程序保留原状态，下一次成功扫描仍与最近一次成功状态比较
