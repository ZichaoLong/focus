# Focus Web 有界正文窗口

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-transcript-window.md`。

## 范围与 owner

本合同适用于已保存的 `history_mode=paginated` 线程。旧格式保留既有兼容读取，
不新增迁移、索引或性能治理。临时子代理线程仍使用既有详情投影。

`WebThreadOpenCoordinator` 持有打开/选择与控制状态；`WebThreadInspectionService`
持有正文读取的 document、selection、backend generation 与 observation 校验；
`transcript_window.py` 只读取冻结的请求并投影条目。浏览器的 `createFocusTranscript`
持有唯一正文窗口，`createFocusHistoryNavigation` 继续持有 Prompt 摘要目录。
`TranscriptRow.vue` 只持有可视区域与测量高度，不持有历史或发送权限。

## 控制状态与正文读取

打开或恢复 paginated 线程使用 `itemsView=summary`。snapshot 的 `turns` 只承载有界的
首个用户 Prompt 摘要，保留 active-turn identity、pending requests、settings 与 selection
receipt。正文通过独立的 `GET /api/threads/{thread_id}/transcript` 加载；正文正在加载或
失败不会撤销已确认的 Composer scope。发送仍要求服务端 `hello`，不能以 WebSocket
`open` 代替连接确认。已确认的发送前 `web_writer_disconnected` 拒绝会重连并保留输入，
不自动重放 prompt。其他未知结果仍遵循 prompt mutation 恢复合同。

正文 query 是封闭集合：可选 `turn_id`、opaque `cursor`、`direction=asc|desc`、`item_id`
与 `full=true|false`。值不得为空、带首尾空白、重复或超过 4096 字符。
`item_id` 必须同时指定 `turn_id` 且不得与 cursor 共用；`full=true` 必须指定 item。
缺省读取全线程最新 40 个条目，以时间正序呈现；前后页使用上游 cursor，不合成 offset。
Prompt 定位读取指定轮次的开头，搜索定位读取指定 item；定位后的翻页范围是该轮次，
可以通过 Prompt 目录转到其他轮次或返回近期消息。

返回 `{runtime_epoch, revision, thread_id, turn_id, turns, older_cursor, newer_cursor, full_text}`。
行携带稳定的 `rawTurnId`、`itemId` 与 `id=<turn>:item:<item>:<segment>`。
普通页只投影请求中的最多 40 个条目，响应上限 2 MiB；单条源展示树最多保留 16384
个文本字符、1024 个节点、12 层深度，投影超过 32 KiB 时退为较短的纯文本预览。
被裁剪的内容必须携 `contentDeferred=true`，不能渲染不完整 Markdown 或伪装成全文。
已有 tool-output omission/deferral 元数据继续受其独立预算约束。

“查看完整内容”使用上游 item anchor 读取一个前驱，再向前读取目标 item，共两次
有界定位请求。必须核对 exact item/turn；目标丢失则报告错误，不能用附近条目代替。
`full=true` 返回空 `turns` 与完整 `full_text`，不应用预览字符上限。用户消息/回复为文本，
reasoning 为完整可见 reasoning，其他条目为源 JSON。完整内容单独显示为可选择文本并
从源字符串复制；关闭、换线程、epoch/access 改变或 dispose 会清除该内容及请求。
这是显式的大内容读取，内存与传输成本取决于用户所选条目。

所有正文读取使用现有 staged boundary；持锁阶段只做准备，不跨上游 I/O。
结算要求同一 document、selection、backend generation、runtime epoch 和本线程 read
observation。其他线程的全局 revision 增长不使本页失效；同线程并发变化仍拒绝陈旧页。
浏览器安装时再次校验身份，回放严格晚于页 revision 的有序事件。旧意图不能覆盖新导航。
正文页不写入服务端 live cache，不持有 writer authority。

## 实时更新、预算与重同步

live read model 继续最多保留 20 个 raw turns；paginated 模式每轮最多 80 个有界条目。
控制摘要刷新保留已经观测到的条目，不把摘要当完整正文替换。发送准备只读取 cached
active-turn identity，不能为了得到 turn id 深拷贝正文。

notification worker 对有界条目投影，coordinator 仅发布变化的 `item_turns` 与有界
`item_order`。每线程保持一个投影 flight 和一个最新 successor；worker 结算仍服从
observation/epoch 校验，successor 执行前冻结最新缓存，不能让旧流文本回退。
stream delta 只更新对应条目。浏览器实时窗口最多 80 行；历史翻页替换窗口，期间的新
实时条目不把历史页面拉回尾部。生命周期与 epoch 变化清理比较缓存；比较缓存最多保留
最近 16 个线程，淘汰只导致下一次重发有界条目，不改变线程事实。控制刷新保留缓存中
已经观测到的子代理任务；冷打开不为了重建全部旧任务扫描历史正文。

每个 socket 待发队列同时受既有 128 条默认计数及 2 MiB 字节预算约束；溢出只排入一条
小型 `socket_backpressure` invalidation，不重放大 payload。它不等同于断开或发送失败。
浏览器控制 snapshot 缓冲最多 256 条/1 MiB 估算字节，正文读取缓冲最多 256 条/512 KiB；
溢出丢弃不完整缓冲并重新读取有界状态。流展示批次最多 256 条/512 KiB，达到上限提前
刷新。正文自动恢复最多三次，间隔 1/2/4 秒，之后保留错误与手动重试入口；不得无限快速
重试、回到整线程读取或重发 prompt。

## 阅读、复制、导出与诊断

正文行在滚动容器可视区上下各约 900px 内挂载，离开后用实测高度占位；选区端点或焦点
所在行保持挂载。无 IntersectionObserver 的环境回退到有界窗口渲染。此策略不使用根层
`content-visibility` 或重挂载整个阅读模式页面。需验证反复进入/退出阅读模式、尺寸变化、
迟到的 Markdown/图片布局、滚动跟随和 Prompt/search 定位。

分页条目的复制按钮只复制该消息，预览不提供冒充全文的复制或回填。浏览器原生查找与
跨离屏区域拖选只能覆盖当前挂载内容；应用的 Prompt/最终回复搜索、按需全文、Markdown/PDF
导出继续使用源数据。导出不从虚拟 DOM 或预览拼接，既有导出范围/完整性限制不变。

页面诊断继续默认关闭。手动开始后追加最多 64 条无 payload 的性能记录，包括正文加载
时长、收到事件的字节量、socket close code、backpressure/buffer overflow，以及浏览器
支持时的 long task 时长。停止后冻结，重新开始清空；不记录 prompt、回复、线程 ID、URL、
cookie 或任意断开原因字符串。

## 上游证据

本实现复用 Codex commit `c248f6d48b97eb4a2aa56147a0b11b7d763278b9` 的
`codex-rs/app-server-protocol/src/protocol/v2/thread.rs` 中 `ThreadTurnsListParams`、
`ThreadItemsListParams`、`ThreadItemsListAnchor` 及 `ThreadResumeParams`，以及
`codex-rs/app-server/src/request_processors/thread_processor.rs` 中 indexed item anchor
到 thread-store 的映射。不修改上游存储或旧线程格式。
