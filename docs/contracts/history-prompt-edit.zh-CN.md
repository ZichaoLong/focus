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

Web 编辑 fork 在发送前核对当前 initialize 握手中的版本与 exact connection generation，目前只接受
0.164.0、0.165.0。未知、旧版或未审阅新版不会退化为全历史 fork；限制只作用于编辑能力，基本启动、创建和对话不变。
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

## Web 编辑并分叉

聊天中的“编辑并分叉”提交 `POST /api/threads/{thread_id}/fork`，body 必须恰好为 `{turn_id,item_id}`；
普通完整 fork 仍使用空 body。浏览器不提交正文作为权威输入。服务用同一 generation 的 `thread/items/list`
读取目标轮首条 `userMessage`，核对 item ID 并取完整内容；不从界面 no、synthetic row ID 或 preview 反推边界。
读取最多 5 秒，分页 cursor 必须前进。只有验证完成才进入既有 `ThreadCreateTransaction`，一次发送
`thread/fork {threadId,beforeTurnId,ephemeral:false,excludeTurns:true,deferGoalContinuation:false}`。
不调用来源 revert、不改变来源选择/owner/绑定，不复制或启动来源 goal，也不自动提交 prompt。

支持 paginated 历史中每轮第一条纯文本 prompt，包括首轮、较早轮次及继承轮次。首轮之前的分支历史可为空。
以下情况在创建前明确拒绝：legacy 历史、坐标缺失/不匹配、同轮补充消息、附件或其他非文本输入、非空 text elements、
无法完整读取、空文本，以及 UTF-8 超过 1 MiB。多个文本片段用换行连接，保留片段原文；不静默丢弃附件或结构化信息。
上游仍原子裁决历史边界；并发回退删除目标时不得 fallback 或猜另一个 turn。

成功响应在普通 fork 字段之外总有 `edit_prompt=null|{turn_id,item_id,text}`，浏览器再次核对来源和目标坐标。
完整原文仅恢复为新分支的未发送草稿，使用已有 `loadComposerRecovery` exact scope、空输入框 gate；不覆盖更新的输入或附件。
若用户创建期间切走，保留其导航，只在对应新分支打开后恢复。handoff 未成功则保留原文和显式恢复入口，成功后删除内存记录；
发送仍由用户通过现有普通 prompt 单 POST/receipt 路径发起。创建/发送 unknown 均不自动重复。
尚未 handoff 的内存文本不保证跨 F5；分支 ID 已知时保留 ID 诊断，以便手动打开。

命名、一次限时列表检查、可关闭的分支可见性提醒沿用
[创建合同](thread-create-local-commit.zh-CN.md#创建后的列表观察与提示)。一页未命中不证明完整目录不存在，
也不承诺重启后自动发现所有空 preview 分支。

## 历史变更与缓存

canonical app-server 的 `thread/reverted` 通知只失效对应线程：推进既有 read observation fence，清除 Web 历史、
token usage 和在途 transcript projection，发布 `thread_invalidated`。不改变已存在 fork 的缓存或历史。
浏览器在既有 event epoch/revision admission 后清除对应正文、prompt 导航、全文/工具与搜索缓存；取消在途旧读取，
再通过正常 projection/read 路径获取新历史。重连或 event gap 的完整 projection reload 同样先清除这些缓存，
避免遗漏回退通知后仍显示旧历史窗口。迟到旧读取、旧 revision 事件不得重新安装截断后内容。

## 验证边界

必须验证 exact boundary、来源保持不变、继承历史、首轮空历史、附件/补充消息的明确拒绝、跨线程导航、草稿不覆盖、
原生回退同一 ID、foreign lease、断线/unknown 不重试，以及 reverted 后缓存刷新。
真实版本的隔离验证与浏览器证据见 [验证记录](../verification/history-prompt-edit-2026-10-28.zh-CN.md)。
