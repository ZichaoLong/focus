# Focus Web 提交时间与被动诊断

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-prompt-timing.md`。

## 时间来源与边界

普通 prompt 的浏览器发送入口在首次 HTTP yield 前记录 `Date.now()`，表示原浏览器发起这次提交的时间，
不是网络送达证明。包含 existing-thread prompt 与新线程首 prompt。主界面仅显示时间，点击展开时间来源、完整本地日期和毫秒。
时间由原设备时钟提供；跨设备查看按查看设备时区格式化。不能用它与服务端时钟相减宣称单向网络延迟。

`codexRecordedAtMs` 来自 app-server 提供的逐条 userMessage `startedAtMs`，缺少开始时可用其
`completedAtMs`，详情标签为“Codex 记录输入”。它与 Focus 或浏览器的接收时间不同，也不是模型供应商送达证明。
没有浏览器提交时间时可以单独显示这项来源；两者都没有则不编造时间。整轮 `startedAt` 不再用于 user 行，
避免同一 turn 内后续 steer 继承第一条 prompt 的时间。assistant 回复起止时间继续遵循
[有界正文窗口合同](./focus-web-transcript-window.zh-CN.md#回复时间与长回复)。

Focus 记录验证请求之后、准备处理之前的 `service_received`，以及实际处理路径上的 prepare、worker、
元数据/目标 RPC 开始与返回、输入 RPC 开始与返回、观察到匹配用户消息、结果结算等阶段。
这些是 Focus 进程的观察；RPC 开始不是 app-server 内部“收到”的时间，RPC 返回也不证明模型上游收到。
每项阶段包含 wall-clock 毫秒与同一 trace 的 monotonic elapsed 毫秒。阶段耗时只用后者；浏览器等待结果
或错误的耗时也使用本机 monotonic 计时。调度等待、RPC 等待都不得宣称为纯网络耗时。

“Focus 收到首个输出”是 Focus 在 RuntimeLoop 接收既有 app-server 通知时，首次观察到非空推理或回复正文的
本机时间。`FocusWebProjection.observe_prompt_notification` 在页面投影合并之前提供内部被动观察入口，
不发布逐 token 的诊断 wire event；`WebPromptTimingRecorder` 唯一持有观察事实。接受正文/推理 delta，
以及实时 item 通知或 turn 通知中首次出现的非空正文/推理；空 item、心跳、推理分隔符和工具 stdout 不算。
它不依赖 `response.created`，也不是模型原始首 token 时刻。普通历史查询不补造首次接收时间。

关联要求实际观察到本次输入 RPC 发起后的新 `turn/started`，且该轮第一个 user item 的 exact `clientId`
对应本次提交，并先于首个输出出现。同轮追加、原生 start-or-steer 竞争、缺少开始事件或先输出后输入均不得
借用该轮输出。第一条符合条件的输出只保存一次，携带类型、turn/item ID、wall-clock 时间及同 trace 的
monotonic elapsed；后续 token 不写诊断库。断线、线程关闭/卸载/回退、观察缓存淘汰或服务停止终止未完成观察。
已保存的首个输出不因重启或后续断线失效。旧记录为“未记录”；持续观察但尚无输出为“尚未观察到”；
中断为“观察中断”；无法建立本次提交关联为“关联信息不足”；明确结束且未观察到输出为“未观察到”。
显式调用 `turn/steer` 的 `steered_input`，以及在已观察的新轮中按 exact clientId 确认是后续用户条目的
`additional_turn_input`，均显示“追加输入，不单独计时”。这描述追加输入方式，不宣称提交成功或模型已处理；
提交结果仍独立展示。缺少开始/首输入事件、仅有 Codex 记录时间或 `mode=start` 均不足以判为追加输入。
既有 `steered_input` 记录采用同一文案；旧记录没有充分原因证据时不回推分类。原始 status/reason 仍保留在复制诊断中。
这些状态不提供发送失败或可重发的证明。

默认详情依次显示“浏览器提交”“Focus 收到提交”“Codex 记录输入”“Focus 收到首个输出”，再显示提交编号；
缺失的前三项时间不编造，第四项无可靠时间时显示上述状态。已有 Codex 记录时间时隐藏重复提交结果；否则
按已有证据显示“Focus 提交结果”，浏览器结果与其不同时才额外显示；服务端记录缺失显示“服务端记录：未找到”。
三个主要耗时、各项 RPC 耗时、阶段时间和内部 reason code 只进入“复制诊断详情”。复制 JSON 包含完整
server/browser、可用的 `codex_recorded_at_ms`、同源计时的 `durations_ms` 和 `model_upstream.collection=not_integrated`。
本实现仍不采集 Codex 到 base URL 的请求遥测，不在默认面板固定展示该能力状态，也不能拆分该链路各方向耗时。

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

诊断库 schema v2 为提交增加 `first_output` JSON；v1 原地加列，旧行默认 `not_recorded`，不修改原提交时间或
关联。新提交才开始被动观察。读取旧进程或已丢失本地观察上下文的 `pending` 时返回 `interrupted`，不假装仍在观察；
当前进程尚无 exact 首输入关联的已接受提交显示 `unassociated`，后续实际事件可以补齐关联。读取只检查诊断上下文，
不恢复订阅、不查询 app-server、不重放请求。

此数据库不是 durable execution ledger、幂等保证或 retry authority。现有
[单 POST 与 result receipt 合同](./focus-web-prompt-mutation-recovery.zh-CN.md)及 Composer 结算不变。
`unconfirmed` 表示缺少已结算的观察；`outcome_unknown` 表示当时结果未知；`succeeded` 只说明 Codex
接受了输入或 Focus 确实观察到对应用户消息；`known_no_effect` 沿用已知未生效分类。
进程重启不把未完成记录说成仍在执行，缺记录/查询失败不证明未发送。详情不提供新的重发操作。

数据库缺失可懒建，锁冲突、损坏、未知 schema 或队列过载只降级诊断，不阻止发送或安装正文；查询失败返回
明确 unavailable，不返回虚假空成功。损坏文件不自动删除/重建；人工删除这份纯诊断库只丢失展示证据。
全部诊断记录按[Focus 记录保留期](./data-retention.zh-CN.md)清理，服务端按最后更新时间，浏览器按提交时间。
活跃 trace 和浏览器在途提交受保护；服务端拒绝重新同步超过当前保留期的浏览器记录。
明确 Web 线程删除仍尽力清理对应诊断，失败不反转已完成的删除。浏览器保留 64 条容量上限，站点清理也会删除本地记录。

## Wire、按需读取与开销

wire v37 引入以下接口；v38 为诊断记录增加必填的 `first_output`，服务与静态资源同版本部署：

- 普通 prompt POST 和新线程创建 POST 的可选 `X-Focus-Prompt-Id`、`X-Focus-Submitted-At` headers；
  existing-thread identity 必须与 body mutation id 一致。原 prompt body 与 effect admission 不变。
- POST `/api/prompt-timings`：闭合 `{records:[{submission_id,thread_id,submitted_at_ms,browser}]}`，每批最多 32 条。
  browser 只接受 `completed_at_ms,elapsed_ms,result,disconnects`。接口只写元数据，不调用 runtime effect port，
  不延长 auth session。使用现有 document authentication、Origin/CSRF 规则。
- GET `/api/prompt-timings/{submission_id}`：`{record:PromptTimingRecord|null}`。
- `first_output.status` 为 `not_recorded|pending|observed|interrupted|unassociated|not_observed`。
  `observed` 闭合字段为 `status,at_ms,elapsed_ms,turn_id,item_id,kind`，`kind=text|thinking`；
  其他状态闭合字段为 `status,reason_code`。浏览器同步不能提交或覆盖该服务端字段。
- GET `/api/threads/{thread_id}/prompt-timings`：最近 32 条 `{records:PromptTimingRecord[]}`，包括没有生成消息的提交。
  两种 GET 只读已保存记录，要求当前认证 document，使用 `Cache-Control: no-store`，不向 app-server 查询。
- `prompt_timing_changed`：全局小通知，detail 只有 submission id，可附 thread id；普通投影仅推进 coordinates，
  不因此重载正文。只有已展开的提交记录列表才自动刷新；单条详情保留本次读取的快照。
- user 行可带 `clientUserMessageId`、`codexRecordedAtMs` 与
  `promptTiming={submissionId,submittedAtMs}`。普通历史读取批量附带摘要，不逐消息发 GET。

详情展开、显式刷新时才读诊断；打开期间不随阶段通知重新读取，收起后不轮询。
“刷新”和“复制诊断详情”按钮保留。刷新失败保留上次快照并标明刷新失败，不将旧数据伪装为最新。
无消息的尝试仍能在默认折叠的“提交记录”中查看。
每条 trace 最多 20 个阶段，writer queue 上限 512，内存 trace 上限 256、已观察 item 去重上限 512。
首输出观察上下文最多保留 256 轮。相同里程碑不重复写，不记录 token、输出正文或每个 stream delta；
正常提交最多发布四个提交里程碑通知和一个首输出观察结果通知。
已打开的列表对事件做 250ms 合并，只保留最近 32 项并限制手机上的面板高度。
已有连接心跳、operator status 与 mutation result 查询保持原规则；此功能不新增按 prompt 的 app-server 轮询。

## 验证与上游证据

核心回归为 `tests/web_runtime/test_prompt_timing.py`、`tests/web_runtime/test_prompt_first_output.py`、`web/test/focus-prompt-timing.test.ts` 与
`web/test/focus-prompt-timing-browser.test.ts`，同时运行既有 prompt authority、Gateway、transcript 和 wire guards。
覆盖本地存储失败、响应丢失、F5、跨 document 同步、跨设备关联、重复身份、fork 隔离、服务重启、数据库损坏、
同 turn 的不同时间、手机展开、按需 GET 与不重放请求。

逐条消息时间证据固定为
[`openai/codex@c248f6d48b97eb4a2aa56147a0b11b7d763278b9`](https://github.com/openai/codex/commit/c248f6d48b97eb4a2aa56147a0b11b7d763278b9)
的 app-server `ThreadItemEntry` 和 user item notifications；其部署可用性沿用正文窗口合同的 capability 判断。
本功能不修改 Codex 的 session、thread history 数据库或配置。
