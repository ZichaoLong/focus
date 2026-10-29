# Focus Web 提交时间与被动诊断

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-prompt-timing.md`。

## 时间来源与边界

普通 prompt 的浏览器发送入口在首次 HTTP yield 前记录 `Date.now()`，表示原浏览器发起这次提交的时间，
不是网络送达证明。包含 existing-thread prompt 与新线程首 prompt。摘要显示“提交”，点击展开完整本地日期和毫秒。
时间由原设备时钟提供；跨设备查看按查看设备时区格式化。不能用它与服务端时钟相减宣称单向网络延迟。

`codexRecordedAtMs` 来自 app-server 提供的逐条 userMessage `startedAtMs`，缺少开始时可用其
`completedAtMs`，标签为“Codex 记录”。它与 Focus 或浏览器的接收时间不同，也不是模型供应商送达证明。
没有浏览器提交时间时可以单独显示这项来源；两者都没有则不编造时间。整轮 `startedAt` 不再用于 user 行，
避免同一 turn 内后续 steer 继承第一条 prompt 的时间。assistant 回复起止时间继续遵循
[有界正文窗口合同](./focus-web-transcript-window.zh-CN.md#回复时间与长回复)。

Focus 记录验证请求之后、准备处理之前的 `service_received`，以及实际处理路径上的 prepare、worker、
元数据/目标 RPC 开始与返回、输入 RPC 开始与返回、观察到匹配用户消息、结果结算等阶段。
这些是 Focus 进程的观察；RPC 开始不是 app-server 内部“收到”的时间，RPC 返回也不证明模型上游收到。
每项阶段包含 wall-clock 毫秒与同一 trace 的 monotonic elapsed 毫秒。阶段耗时只用后者；浏览器等待结果
或错误的耗时也使用本机 monotonic 计时。调度等待、RPC 等待都不得宣称为纯网络耗时。

本实现不采集 Codex 到 base URL 的 HTTP/SSE/WebSocket 请求遥测，详情必须显示“尚未采集”。
它不能判断该链路的发送与回复各用了多久，也不能从首个输出反推精确的上游收件时间。

## 持久化、关联与 authority

浏览器 `createPromptTimingStore` 在 `localStorage` 的 `focus-web.prompt-timings.v1` 中保留最近 64 次记录：
submission UUID、thread id、提交时间、浏览器完成/错误时刻、等待耗时、当次等待期间事件连接断开次数，
以及本地同步版本。没有 prompt 正文、附件、token 或可重放的请求。写入失败降级内存并显示提示，不阻止提交。
完成请求、连接 hello 或用户刷新记录时可补同步；刷新页面途中留下的不完整记录和替换 document identity
后的旧记录也可同步。不完整不等于失败，也不补造已收到结果。

服务部署机的 `data_dir/web_prompt_timing.sqlite` 由 `WebPromptTimingStore` 持有，唯一用途是跨页面、设备和
进程重启保留展示证据。`WebPromptTimingRecorder` 在独立有界 worker 中写 Focus 观察，Gateway 的同步接口只可
写浏览器字段；普通正文读可以保存已实际观察到的 exact item 关联。浏览器字段绝不能建立服务端收到时间、
服务结果、阶段、epoch 或消息关联。首次有效观察固定原提交时间与写入身份，重复/冲突 ID 不覆盖旧观察。

existing-thread UUID 等于原 `mutation_id`；新线程首 prompt 在浏览器生成 UUID，server 派生
`client_user_message_id=focus-web:<UUID>`。只按该 exact client id 与 thread 关联，再保存实际的
`(thread_id, turn_id, item_id)`，供重启后不再携 clientId 的历史使用。不比较正文、顺序、邻近时间，
也不把 fork 中复制的 clientId 当作原线程关联。

此数据库不是 durable execution ledger、幂等保证或 retry authority。现有
[单 POST 与 result receipt 合同](./focus-web-prompt-mutation-recovery.zh-CN.md)及 Composer 结算不变。
`unconfirmed` 表示缺少已结算的观察；`outcome_unknown` 表示当时结果未知；`succeeded` 只说明 Codex
接受了输入或 Focus 确实观察到对应用户消息；`known_no_effect` 沿用已知未生效分类。
进程重启不把未完成记录说成仍在执行，缺记录/查询失败不证明未发送。详情不提供新的重发操作。

数据库缺失可懒建，锁冲突、损坏、未知 schema 或队列过载只降级诊断，不阻止发送或安装正文；查询失败返回
明确 unavailable，不返回虚假空成功。损坏文件不自动删除/重建；人工删除这份纯诊断库只丢失展示证据。
已关联消息的时间保留到明确删除对应 Web 线程时清理；未关联记录在后续元数据同步时清理超过 90 天的项。
Web 删除后的清理是尽力而为，失败不反转已完成的删除；其他设备尚未同步的本地记录可再次上传为浏览器观察。
浏览器保留范围与服务端独立，清理站点数据或超过 64 条会淘汰本地记录。

## Wire、按需读取与开销

wire v37 增加：

- 普通 prompt POST 和新线程创建 POST 的可选 `X-Focus-Prompt-Id`、`X-Focus-Submitted-At` headers；
  existing-thread identity 必须与 body mutation id 一致。原 prompt body 与 effect admission 不变。
- POST `/api/prompt-timings`：闭合 `{records:[{submission_id,thread_id,submitted_at_ms,browser}]}`，每批最多 32 条。
  browser 只接受 `completed_at_ms,elapsed_ms,result,disconnects`。接口只写元数据，不调用 runtime effect port，
  不延长 auth session。使用现有 document authentication、Origin/CSRF 规则。
- GET `/api/prompt-timings/{submission_id}`：`{record:PromptTimingRecord|null}`。
- GET `/api/threads/{thread_id}/prompt-timings`：最近 32 条 `{records:PromptTimingRecord[]}`，包括没有生成消息的提交。
  两种 GET 只读已保存记录，要求当前认证 document，使用 `Cache-Control: no-store`，不向 app-server 查询。
- `prompt_timing_changed`：全局小通知，detail 只有 submission id，可附 thread id；普通投影仅推进 coordinates，
  不因此重载正文。只有已展开的对应详情/记录列表才刷新诊断。
- user 行可带 `clientUserMessageId`、`codexRecordedAtMs` 与
  `promptTiming={submissionId,submittedAtMs}`。普通历史读取批量附带摘要，不逐消息发 GET。

详情展开、显式刷新时才读诊断；收起后不轮询。无消息的尝试仍能在默认折叠的“提交记录”中查看。
每条 trace 最多 20 个阶段，writer queue 上限 512，内存 trace 上限 256、已观察 item 去重上限 512。
相同里程碑不重复写，不记录 token、输出正文或每个 stream delta；正常提交最多发布四个诊断里程碑通知。
已打开的列表对事件做 250ms 合并，只保留最近 32 项并限制手机上的面板高度。
已有连接心跳、operator status 与 mutation result 查询保持原规则；此功能不新增按 prompt 的 app-server 轮询。

## 验证与上游证据

核心回归为 `tests/web_runtime/test_prompt_timing.py`、`web/test/focus-prompt-timing.test.ts` 与
`web/test/focus-prompt-timing-browser.test.ts`，同时运行既有 prompt authority、Gateway、transcript 和 wire guards。
覆盖本地存储失败、响应丢失、F5、跨 document 同步、跨设备关联、重复身份、fork 隔离、服务重启、数据库损坏、
同 turn 的不同时间、手机展开、按需 GET 与不重放请求。

逐条消息时间证据固定为
[`openai/codex@c248f6d48b97eb4a2aa56147a0b11b7d763278b9`](https://github.com/openai/codex/commit/c248f6d48b97eb4a2aa56147a0b11b7d763278b9)
的 app-server `ThreadItemEntry` 和 user item notifications；其部署可用性沿用正文窗口合同的 capability 判断。
本功能不修改 Codex 的 session、thread history 数据库或配置。
