# Focus Web 有界正文窗口

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-transcript-window.md`。

## 范围与 owner

本合同适用于已保存的 `history_mode=paginated` 线程。旧格式保留既有兼容读取，
不新增迁移、索引或性能治理。临时子代理线程仍使用既有详情投影。

`WebThreadOpenCoordinator` 持有打开/选择与控制状态；`WebThreadInspectionService`
持有正文读取的 document、selection、backend generation 与 observation 校验；
`transcript_window.py` 只读取冻结的请求并投影条目。浏览器的 `createFocusTranscript`
通过 `TranscriptPageWindow` 持有唯一正文窗口，`createFocusPromptHistory` 持有 paginated Prompt 目录，
`createFocusHistoryNavigation` 保留旧格式的摘要导航。
`TranscriptRow.vue` 只持有可视区域与测量高度，不持有历史或发送权限。

## 控制状态与正文读取

打开或恢复 paginated 线程使用 `itemsView=summary`。snapshot 的 `turns` 只承载有界的
首个用户 Prompt 摘要，保留 active-turn identity、pending requests、settings 与 selection
receipt。正文通过独立的 `GET /api/threads/{thread_id}/transcript` 加载；正文正在加载或
失败不会撤销已确认的 Composer scope。发送仍要求服务端 `hello`，不能以 WebSocket
`open` 代替连接确认。已确认的发送前 `web_writer_disconnected` 拒绝会重连并保留输入，
不自动重放 prompt。其他未知结果仍遵循 prompt mutation 恢复合同。

正文 query 是封闭集合：可选 `turn_id`、opaque `cursor`、`direction=asc|desc`、`item_id`、
`full=true|false`、`view=transcript|prompts` 与 `source_cursor`。值不得为空、带首尾空白、
重复或超过 4096 字符。`item_id` 必须指定 `turn_id`；`full=true` 必须指定 item；
`source_cursor` 只用于 full 且排斥 cursor。缺省读取全线程最新 40 个条目，以时间正序
呈现；前后页使用上游 cursor，不合成 offset。Prompt 与搜索都定位 exact item，不能将
同轮追加消息映射到首条 Prompt；定位时按已知 `turn_id` 限定查找范围，找到后继续在全线程范围翻页。
后续浏览 cursor 请求不携 turn filter。索引定位先读取目标的 inclusive 字符串 cursor，再以此读取
全线程页，不解码或合成上游 cursor。

返回 `{runtime_epoch, revision, thread_id, turn_id, view, target_pending, turns, older_cursor,
newer_cursor, full_text}`。行携带稳定的 `rawTurnId`、`itemId` 与
`id=<turn>:item:<item>:<segment>`。普通页最多读取 40 个源条目。Prompt、steer、
assistant 中间/最终回复及可见 reasoning 保留完整文本，不按字符、节点、段落或同条目
字段总和裁成预览。页的 2 MiB 序列化目标只决定一次加载多少完整条目：超出时从同一
上游 anchor/cursor 以更小的 limit 重读，使用新返回的真实前后 cursor。单条超过目标时
仍完整准入，不能截断、跳过、无限重试或制造分页缺口。完整源条目的网络/解析成本与
其大小有关；页数与缓存预算不等同于模型输出限制。

所有工具条目（包括运行中的工具）只投影一行名称、状态和调用短摘要，统一携
`contentDeferred=true`，只有一个无边框“查看详情”入口。名称与参数摘要各至多 512
字符，不发送输出、diff、媒体正文或详细 commandActions。源树的 16384 字符、1024
节点、12 层预算只服务工具摘要，优先保留身份和调用字段；它不裁剪正文。一个多文件
修改源条目显示一行文件数量摘要，详情读取整条记录。工具名称仍由既有 projection 拥有。
正文不携 `contentDeferred`，没有“超长预览／查看全文”中间状态。

已完成命令及单文件修改使用专用详情，首次点击直接请求 `view=full`，不先请求 preview。
其他工具和运行中工具使用 exact item 的 `full=true` 源 JSON；两者都优先使用逐条 anchor，
不因已有 sourceCursor 而重读整页。完整内容读取失败可显式重新读取；关闭、换目标、
换线程或 epoch/access 变化取消请求并清空唯一详情槽。正在运行的通用详情明确显示
本次读取的记录，可手动重新读取；收到该工具完成事件时，只对已打开详情刷新一次，
不轮询未打开的工具。上游尚未保存的内容不能伪装成完整持久化输出。

Prompt 目录首次打开或侧栏被使用时，`view=prompts` 从最新条目分批向前读取 userMessage，
包括同轮追加/steer 消息，每条只返回至多 160 字符的短标题及裁剪提示。此 view 只接受
全线程、desc 的 cursor 分页。每个 HTTP 请求最多顺序读取四页、每页 100 个源条目；
遇到含用户消息的页即返回，空页仍返回推进后的 cursor。浏览器保留至多 200 条，达到
上限明确提示。首次使用自动读取一批；每批取得约 20 条新标题（不拆分服务端页）或发出
8 次请求即停止，后续通过“加载更多 Prompt”从原 cursor 继续。重新打开或聚焦目录不继续
后台扫描；批内保留已显示条目的位置，完成、失败或暂停时一次性发布已读取的标题。
扫描中显示加载状态，关闭目录或点击目标暂停；目标定位显示进行中状态，已有标题始终可选。
失败保留已有标题并支持重试；换线程、epoch/access 变化和 dispose 取消请求。目录读取不阻塞
初始打开/发送，也不向浏览器传输工具、推理和回复正文，不使用 SQLite 或 rollout 旁路。
目录扫描与目标定位的 cursor 记录均至多保留最近 256 个，避免超大线程放大浏览器内存。
控制 snapshot 保留已观测的 userMessage 短标题与 item identity；实时追加消息按 ID 去重，
不随正文窗口淘汰而消失。旧格式仍用原有摘要目录，不加入此扫描。

普通页可携 `sourceCursor`，其 envelope 只封装上游返回的 inclusive backwards cursor、
原 turn scope、direction 和实际页大小（1..100）；不是授权凭据，不合成上游 cursor。
显式携带此参数的全文请求按原参数重读并核对 exact item/turn。官方浏览器优先使用
item anchor 读前驱再读目标，专用工具全文读取复用同一 anchor owner。
仅当旧服务明确拒绝对象 cursor（expected a string）时，回退到
有界字符串 cursor 分页，全文读取与正文定位都只扫描目标轮次；未找到但可继续时返回
`target_pending=true`，浏览器可取消地继续读取。正文定位找到目标后，使用该页的 inclusive
cursor 重开全线程页，再提供跨轮次浏览。其他上游错误不作为兼容信号。目标丢失则报告错误，不能用附近条目代替。

`full=true` 找到目标后返回空 `turns` 与完整 `full_text`，不应用预览字符上限。用户消息/
回复为文本，reasoning 为完整可见 reasoning，其他条目为源 JSON。完整内容单独显示为
可选择文本并从源字符串复制；关闭、换线程、epoch/access 改变或 dispose 清除内容及请求。
工具源 JSON 的详情同时显示选中工具的名称和调用摘要；此上下文随请求建立，在加载和
错误状态中保留，与内容一同清除。旧请求不得覆盖新工具的内容或标题。
Focus 合成的当前计划与整轮 diff 标记为 live-only，其完整内容由已有 live read model
按 exact turn/item 冻结，通过相同的 document/epoch/observation 结算，不扫描持久化历史、
不建立另一份长期内容缓存。此类记录随 live cache 生命周期消失。
陈旧读取至多原请求重试一次，其他错误显示具体原因。显式全文读取的内存与传输成本取决于
所选条目及其有界来源页。

## 回复时间与长回复

`agentMessage` 展示行及其 text block 携 `reply={state, startedAtMs?, completedAtMs?}`。
`state` 为 `unknown|generating|complete`；时间是 app-server 逐条 item 的 Unix 毫秒，
非负整数且不超过 JavaScript Date 上限。历史页读取 `ThreadItemEntry` 的可空字段；实时
`item/started`、`item/completed` 的 notification 顶层时间由 read model 保存，完成与
同条目的后续 turn snapshot 合并保留开始时间。无完成时间的历史项为 unknown，不猜测仍在生成。
时间缺失时不以轮次开始、浏览器接收或页面打开时间补值。工具卡不增加时间标签。

每个中间/最终文本回复显示低强调的本地时间，优先完成时间；仅有开始时间则显示开始时间，
明确观测到正在生成时附生成提示。点击展开完整日期、已有的开始/完成时间，以及两者有序
时的逐条用时。此数据与原有整轮 duration 分开，缺时间的旧回复不显示虚构标签。

正文随页完整加载，不使用独立的回复全文请求或第二份回复 LRU。实时文字继续追加到
所属条目，跨过 16384 字符也不停止显示或等待 item 完成。可见 reasoning 在主界面完整
展开，随主滚动容器阅读，不使用五行内部滚动窗口或自动折叠。旧格式线程保留原有展示。
复制和回填使用完整已加载正文；时间标签继续独立遵循真实 item 的开始/完成状态。

达到 16384 字符的完整 Markdown 使用共享配置一次解析，按顶层完整结构分组（目标 12000 字符、至多 24 个
顶层节点），再按可视范围挂载；单个表格、列表、公式或代码块允许超出分组目标，不切断
语法结构。解析保留全文引用上下文；diff fence 显示完整原始增删行。各组离屏使用实测
高度，测量随有界正文行保存；可见组纳入既有滚动锚点，布局补偿仍由正文唯一 owner 执行，
不得撤销触摸/惯性位移。没有 IntersectionObserver 时回退到完整回复渲染。

所有正文读取使用现有 staged boundary；持锁阶段只做准备，不跨上游 I/O。
结算要求同一 document、selection、backend generation、runtime epoch 和本线程 read
observation。其他线程的全局 revision 增长不使本页失效；同线程并发变化仍拒绝陈旧页。
浏览器安装时再次校验身份，回放严格晚于页 revision 的有序事件。旧意图不能覆盖新导航。
正文页不写入服务端 live cache，不持有 writer authority。

## 实时更新、预算与重同步

live read model 继续最多保留 20 个 raw turns；paginated 模式每轮最多 80 个条目，并以
源字符串长度乘二加结构开销估算 8 MiB 驻留目标。超出时淘汰完整旧条目，最新单条可
超过该目标；正文不截断。
控制摘要刷新保留已经观测到的条目，不把摘要当完整正文替换。发送准备只读取 cached
active-turn identity，不能为了得到 turn id 深拷贝正文。

notification worker 对有界条目投影，coordinator 仅发布变化的 `item_turns` 与有界
`item_order`。每线程保持一个投影 flight 和一个最新 successor；worker 结算仍服从
observation/epoch 校验，successor 执行前冻结最新缓存，不能让旧流文本回退。
正文 stream delta 只更新对应条目。运行中的 command/file output、MCP progress 和 plan
文字 delta 不向普通正文窗口发布；工具开始/完成及状态摘要继续更新。子代理任务概览
只携身份和状态，不通过 tasks 字段重复发送 prompt、progress、result 或 output。浏览器正文窗口按需累积至多 10 个相邻源页，并按每条展示行 JSON 字符串长度乘二估算，
施加 8 MiB 总数据目标；先达到任一上限就淘汰远离浏览方向的整页。单个当前页可超过
字节目标；单条超大正文仍完整可读，离开后随页面淘汰，不因其大小反复重同步。不预取十页，不另存
整线程正文。反向翻阅仍在窗口内的内容不发请求。反向 cursor 的 inclusive anchor 按稳定
ID 去重并更新；保留窗口两端的真实 cursor，淘汰不能制造缺口。迟到页面不得淘汰用户
当前可见锚点所在页；必要时放弃新到达的远端页。仅剩锚点页与一个相邻页时，允许暂时
超过字节目标，使用户能滚出大条目；锚点移开后可淘汰旧页。实时尾页至多 80 行，超出后执行有界
head 重同步；历史窗口不因实时条目到达而跳到最新。

上下自动加载都要求真实用户向该方向浏览，并进入滚动容器边缘约 300px 的区域。
一次只允许一个正文请求，消费滚动意图后不因 observer/布局变化、Prompt 定位或页面
仍然不足一屏而连续请求；请求进行中不累积下一次自动加载意图。错误保留已有窗口并
阻止自动重试，边界按钮允许显式重试。向上插入、向下追加和远端淘汰时，以首个可见
条目的 ID 与像素偏移保持阅读位置，虚拟行测量更新也遵循同一锚点。连续正文的应用锚点
是唯一布局补偿来源，禁用该容器的原生滚动锚定；校正只补偿条目在内容坐标中的位移，
不能撤销触摸或松手后的惯性滚动。滚动时更新可见锚点，避免持续恢复分页时的旧位置。新用户输入、Prompt
定位和线程切换取代旧滚动意图。只有到达全线程真正最新端才恢复实时跟随；历史页底部
不能被当作最新端，未展示的新实时条目通过向下加载补齐。生命周期与 epoch 变化清理比较缓存；比较缓存最多保留
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
行内的 Markdown renderer 禁用自身 `content-visibility:auto` 和固有占位尺寸，避免与外层
虚拟行重复估算高度；重新挂载短消息不能先变成 600px 占位，再因可见性变化反复卸载/挂载。

分页条目的复制按钮只复制该完整消息。浏览器原生查找与
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
到 thread-store 的映射，以及 `codex-rs/thread-store/src/local/thread_history/segment_paging.rs`
中的 inclusive backwards cursor。对象 anchor 来自 commit
`de9e78e3e7caed0fdd75d20ae617faa646dfef3c`；实际 npm 0.156.1 只接受字符串，0.160.0
已验证接受对象 anchor。不得由开发分支源码推断已部署版本的能力。不修改上游存储或旧线程格式。

逐条时间的协议证据为同一 pinned commit 的 `ThreadItemEntry`（`v2/thread.rs`）与
`ItemStartedNotification`、`ItemCompletedNotification`（`v2/item.rs`）；引入提交为
`772abc9425d4bf4c2802456365785378811e7d3d`。本机 npm 0.160.0 已验证返回该字段；
旧 producer 没有记录的时间仍可为空。
