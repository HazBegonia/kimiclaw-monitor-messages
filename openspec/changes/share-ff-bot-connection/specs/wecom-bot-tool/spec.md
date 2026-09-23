## Purpose

企微 bot 工具层：对调用方暴露高层推送接口，内部封装共享长连接的全部编排（按需连接发送、踢线后拉活对端、失败退避、欠账保险），使通知器与未来脚本不接触协议细节即可安全共用同一 FF 机器人，并为钉钉、邮件等新渠道预留同层扩展位。

## ADDED Requirements

### Requirement: 高层推送接口

工具层 MUST 暴露高层推送接口 `push_markdown(text)`：调用方只传正文；连接建立、认证、发送、回执确认、断开、以及拉活对端连接，MUST 全部由工具层内部完成。调用方代码 MUST NOT 出现协议帧、凭证或连接对象。

#### Scenario: 一次推送全流程

- **WHEN** 调用方调用 `push_markdown` 且企微侧正常
- **THEN** 消息送达目标群，对端连接随后被恢复，调用方仅收到成功结果

#### Scenario: 发送失败也拉活

- **WHEN** 发送过程中连接异常或回执非 0
- **THEN** 本次记为失败并向调用方返回错误，对端连接仍被恢复，不留双方断开的无人值守状态

### Requirement: 踢线拉活编排

工具层 MUST 在每次使用共享连接（建立即踢下对端）之后恢复对端的常驻连接：恢复 MUST 通过修改 gateway 配置触发通道热重载（`channels.wecom.enabled` 先 false 后 true）完成，且 MUST 在自身连接断开之后执行，避免恢复动作反踢自己的发送。gateway 不可达时 MUST 记欠账而非报错退出。

#### Scenario: 发完即拉活

- **WHEN** 推送发送完成并断开连接
- **THEN** 工具层随即触发对端通道热重载，对端在数秒内重新在线

#### Scenario: gateway 不可达记欠账

- **WHEN** 拉活时 gateway 未运行
- **THEN** 拉活记入欠账账本等待兜底，本次推送结果不受影响

### Requirement: 欠账保险

工具层 MUST 在每次建立共享连接前向账本文件（`state/bot-tool-state.json`）记录「待拉活」欠账，拉活成功后清偿；并 MUST 暴露 `ensure_companion_alive()` 供常驻循环每轮调用：发现未清偿且已到期的欠账即执行拉活。推送进程在拉活前崩溃 MUST NOT 导致对端永久下线。

#### Scenario: 崩溃后下轮补拉活

- **WHEN** 推送进程在建立连接后、拉活前崩溃
- **THEN** 后续任一轮调用 `ensure_companion_alive()` 时发现欠账并执行拉活，对端恢复在线

#### Scenario: 无欠账空操作

- **WHEN** 账本无未清偿欠账
- **THEN** `ensure_companion_alive()` 不产生任何副作用

### Requirement: 发送失败退避

发送失败 MUST 进入指数退避（初始 5 秒，逐次倍增，5 分钟封顶）调度重试，退避未到期 MUST NOT 发起连接；发送成功后退避状态 MUST 清零。退避状态持久化在账本文件中，进程重启后不丢失。

#### Scenario: 连续失败退避拉长

- **WHEN** 发送连续失败
- **THEN** 相邻重试间隔按 5s→30s→5m 的退避表拉长，不以固定高频重试

#### Scenario: 成功清零

- **WHEN** 退避中的发送最终成功
- **THEN** 退避状态清零，下一次发送无退避延迟

### Requirement: 渠道扩展位

工具层 MUST 将渠道相关逻辑收敛在层内：新增渠道（钉钉、邮件等）或新增 bot 操作（收件箱落盘等）MUST NOT 要求修改现有调用方的调用代码。

#### Scenario: 新渠道不改调用方

- **WHEN** 工具层新增一个通知渠道
- **THEN** 现有调用方代码无需修改即可继续工作
