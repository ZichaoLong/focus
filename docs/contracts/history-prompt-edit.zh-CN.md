# 历史 prompt 编辑

文档角色：中文规范源。英文同步副本：`docs/contracts/history-prompt-edit.md`。

## 事实源与协议

Codex 拥有线程、持久历史和目录。Focus 不扫描或改写 Codex 私有数据库，不维护持久线程索引、历史副本或
跨重启编辑日志。Web 未发送草稿继续由现有 Composer 管理，创建期间的文本 handoff 仅留在当前 document 内存。

本能力固定审阅 Codex `0.164.0`：
[`fe3b29455488c2e189e43ad5526a107900c5e1b7`](https://github.com/openai/codex/commit/fe3b29455488c2e189e43ad5526a107900c5e1b7)。
0.164.0 和 0.165.0 的实际二进制导出均有 `thread/revert {threadId,beforeTurnId}`、`thread/reverted {threadId}`
及 `thread/fork.beforeTurnId`。前者改写同一线程的持久历史，后者创建独立 ID；均排除目标轮及其后续历史。
`thread/rollback` 已不在这两个版本的协议清单中，Focus 不做名称替换或 fork fallback。

Web 历史编辑采用同一个公开 `thread/revert`，不再使用实验性的 `thread/fork.beforeTurnId`，也不按版本字符串
维护编辑 fork 白名单。接口不支持时原样失败，不退化为分叉或其他回退方法；当前实现以 0.164.0、0.165.0 的已验证语义为基线。
完整升级期 schema 基线采用 0.164.0；0.165.0 只验证本合同的协议子集，不声称其所有新增能力已被接入。

固定上游实现：
[原生 TUI 选择与完整输入验证](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/tui/src/app_backtrack.rs)、
[TUI revert 与结果不明处理](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/tui/src/app/event_dispatch.rs)、
[app-server fork/revert](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/app-server/src/request_processors/thread_processor.rs)、
[继承历史、回退与运行中 turn 测试](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/app-server/tests/suite/v2/thread_revert.rs)。

## fcodex 原生回退

原生 TUI 的历史编辑原样发送 `thread/revert`，不变成 fork。此原生协议只支持持久 paginated 线程；
legacy/ephemeral 的上游拒绝原样保留，不做降级。Focus 只接受无额外字段的 exact
`threadId + beforeTurnId`，目标必须是权威 direct root，发起连接必须已 attach；沿用现有 control writer gate，
foreign exclusive/autonomous lease 不因编辑而绕过。请求通过现有 tracked request 结算，不新建 writer、历史 owner 或重发日志。
成功 response 必须对应原线程 ID；错误 target、断线、畸形 response 是结果不明。
上游 `-32600/-32601/-32602` 保留验证/不支持错误；其他 revert 错误可能发生于持久修改之后，按 unknown 结算。
proxy 保留原错误给 TUI，不自动重发。

上游 revert 会停止当前 runtime（可中断正在运行的 turn），替换持久历史，再以同一 ID 恢复运行时和订阅。
它不回滚文件改动。普通 Web/fcodex 输入不持有 exclusive lease，Focus 不另造线程锁或承诺“其他前端绝无运行中工作”。
无 foreign lease 时保留该原生行为；原生 TUI 拒绝选择仍在进行中的目标轮，但后续当前 turn 仍可能被回退操作中断。

TUI 自行加载历史并验证输入对应的真实 turn/item；Focus 只运输最终真实 ID，不保存界面序号或截断文本映射。
原生 TUI 拒绝独立编辑同轮补充消息；其本地图片、远程图片、text elements 和 mention bindings 的恢复由对应版本 TUI
拥有。Focus 不把这些内容降成文本，也不把 Web 的纯文本边界强加给原生 TUI。

revert 的内部 reload 不调用 resume 的 idle-goal continuation；goal 的持久状态不由 Focus 清除或改写。
之后明确 resume/start 的自动续跑和准入继续受既有 owner/goal 合同约束；不承诺原生回退取消目标。

## Web 回退并编辑

聊天中的“回退并编辑”采用原生语义：保留当前线程 ID，将有效历史替换为目标轮之前的前缀，再恢复原 prompt
供用户编辑。目标轮及其后续轮不再属于该线程的当前有效历史；其他打开该线程的前端同样受影响，运行中的普通 turn
可能被中断。文件改动和 goal 状态遵循上游，不由 Focus 回滚或取消。线程列表的完整 fork 是独立操作，仍保留来源历史。

浏览器先请求 `GET /api/threads/{thread_id}/history-prompt?turn_id=...&item_id=...`。
服务通过同一 connection generation 的 `thread/items/list` 读取目标轮首条 `userMessage`，核对真实 item ID 并返回
`{thread_id,turn_id,item_id,text}`。读取最多 5 秒，cursor 必须前进；不使用显示序号、synthetic ID 或截断 preview。
这一读取不修改历史，也不创建持久 prepare 记录、token 或第二份历史。

浏览器核对全部坐标并将完整原文保留在当前 document 内存，之后才发送一次
`POST /api/threads/{thread_id}/revert {turn_id}`。读取期间导航或 scope 已改变则取消尚未发送的回退。
后端复用现有 direct-root 准入、control writer gate 和 process-local unknown registry，使用发送前捕获的 exact connection
执行 `thread/revert {threadId,beforeTurnId}`；不另造线程锁，不绕过 foreign exclusive/autonomous lease。
成功返回 `{accepted:true,thread_id}`，必须是原 ID。上游原子决定边界；目标已被并发回退移除时保留拒绝，不猜其他轮次。

Web 原文恢复限持久 paginated 历史中每轮首条纯文本 prompt，包括首轮、较早轮次和继承轮次。首轮回退后历史可为空。
准备阶段明确拒绝 legacy、坐标缺失或不匹配、同轮补充消息、附件及其他非文本输入、非空 text elements、无法完整读取、
空文本及 UTF-8 超过 1 MiB；多个文本片段用换行连接，不静默丢弃结构化内容。

确认成功并刷新当前历史后，原文通过已有 `loadComposerRecovery` 的 exact scope、空输入框 gate 恢复为未发送草稿。
不覆盖新的文字或附件，不抢回请求期间发生的导航；切回原线程后才尝试恢复。无法自动恢复时保留原文和显式恢复入口；
已有待恢复原文时不接受另一次编辑。普通发送仍要求用户明确操作，沿用现有 prompt 路径。

上游 `-32600/-32601/-32602` 保留验证或不支持错误；其他 revert 错误可能发生在持久提交之后，按现有 unknown control
机制结算。断线、超时和畸形结果同样不自动重试，也不 fallback 到 fork。浏览器在发出 mutation 前已经保留原文，
因此 HTTP response 丢失仍可显示并手动恢复；结果不明时刷新历史，不自动恢复到输入框。未交接的内存原文不保证跨 F5。

完整 fork 的 HTTP body 只能为空，其返回不再携 `edit_prompt`；命名及列表可见性提示只属于完整 fork。

## 历史变更与缓存

canonical app-server 的 `thread/reverted` 通知，以及 Web 已确认或结果不明的回退 response，只失效对应线程：推进既有 read observation fence，清除 Web 历史、
token usage 和在途 transcript projection，发布 `thread_invalidated`。不改变已存在 fork 的缓存或历史。
浏览器在既有 event epoch/revision admission 后清除对应正文、prompt 导航、全文/工具与搜索缓存；取消在途旧读取，
再通过正常 projection/read 路径获取新历史。重连或 event gap 的完整 projection reload 同样先清除这些缓存，
避免遗漏回退通知后仍显示旧历史窗口。迟到旧读取、旧 revision 事件不得重新安装截断后内容。

## 验证边界

必须验证 exact boundary、同一 ID、继承历史、首轮空历史、附件/补充消息的明确拒绝、先保留原文再 mutation、
跨线程导航与草稿不覆盖、foreign lease、断线/unknown 不重试，以及 reverted 后缓存刷新。
上游真实版本的既有隔离证据见 [验证记录](../verification/history-prompt-edit-2026-10-28.zh-CN.md)；
当前 Web 路径由 `test_history_prompt_edit.py`、`test_history_edit_gateway.py`、`test_codex_thread_revert.py`
与 `focus-history-edit*.test.ts` 覆盖。
