# Focus Web 问答导出范围

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-summary-export.md`。

## 范围与内容

所有问答 Markdown 和打印／另存为 PDF 入口共用 `FocusThreadActions.vue` 的两项独立选择：
范围 `all`（默认）、`last_turn`、`selected`；内容 `qa`（默认）、`final_answers`、`prompts`。
JSONL 仍是独立的整线程数据导出。

- `all` 按服务端历史顺序扫描全部可见轮次。
- `last_turn` 从最新向前寻找含 `userMessage` 的一轮，跳过纯系统／压缩轮；不以当前页面、
  最后一条 assistant 消息或最后一个已完成轮次替代。没有用户提问轮次时显式失败。
- `selected` 接收同一线程的 1..100 个不同轮次 ID，以服务端历史顺序合并，
  不采用用户勾选顺序。任何 ID 缺失或属于其他线程时整次失败。

内容规则如下：

| 内容 | 全部轮次 | 最后一轮／勾选轮次 |
| --- | --- | --- |
| `qa` | 保持首条用户提问的摘要导出；只在轮次已完成时加入最终回复 | 包含该轮全部用户文本与最终回复；未完成或缺少最终回复时整次失败 |
| `final_answers` | 仅导出已完成轮次的最终回复，跳过没有最终回复的轮次 | 仅导出所指轮次的最终回复；未完成或缺失回复时整次失败，不回退其他轮次 |
| `prompts` | 包含每轮全部用户文本，跳过没有文本提问的轮次 | 包含所指轮次全部用户文本；没有文本提问时整次失败 |

`prompts` 允许生成中、失败、中断轮次中已经存在的用户提问。`prompts` 的所有范围均保留同轮补充／steer，
各次输入以空行分隔；不输出 assistant 正文。`final_answers` 连轮次标题也不能包含提问摘录。
这两种单独内容导出若没有任何可导出正文，应明确失败，不下载空文档。

最终回复优先最后一个 `final_answer`；已完成旧记录没有明确 final 时，兼容最后一个 phase
为空的 agent 消息。明确的 `commentary` 和 `partial_answer` 不成为最终回复，未完成轮次的
phase 为空消息也不成为最终回复。旧记录缺失的 phase 无法重建，兼容规则不等于确认上游曾
发出 final 标记。保持附件 envelope 投影与失败规则，不导出工具、reasoning、hook 或非文本
附件内容。每个导出轮次编号从 1 开始，正文不截断；文件名和文档标题规则不变。

## 选择列表与浏览器状态

`exportTurnSelection.ts` 持有弹窗内选择，`ExportTurnPicker.vue` 展示一页轮次和可展开的所选内容。
列表按轮次归组、从新到旧分页，每页最多 20 个源轮次，不依赖聊天正文窗口或 200 条 Prompt
目录。系统轮可使某页没有问答，仍允许沿返回 cursor 继续；不宣称空页代表历史结束。
列表只提供提问／回答的短摘要及轮次状态，展开时按相同导出规则按需取得整轮所选内容。

勾选在翻页后保留；最多选 100 轮，显示已选数量、清空和“全选本页”。后者只选择本页
当前内容模式可导出的轮次，不隐式选择未读取历史，也不在超限时静默只选一部分。未完成轮次显示
状态，仅 `prompts` 允许新勾选。切换内容保留选中 ID；若已选未完成轮次不能用于新的内容模式，
显示数量并禁止确认，由用户取消选择或改回仅 Prompt，不静默丢弃选择。列表状态仅供展示，导出仍由后端重新验证。列表翻页失败保留现有页与
选择，重试同一失败页；错误或未加载状态不能被当作完整目录。

打开弹窗时固定线程 ID、标题与建议文件名。选择、cursor 和预览仅保存在当前弹窗内存中；
关闭或卸载取消在途读取、清空状态，迟到响应不能覆盖新弹窗或新目标。预览最多保留一轮，
翻页、切换内容或关闭预览时取消在途请求并清理；预览按当前内容模式读取。选中 ID 集合不随聊天虚拟化、滚动或正文淘汰丢失。
范围／预览／保存共用既有导出互斥。打印先选择范围、内容和标题，确认点击中同步打开预览，
再异步取得完整选定 Markdown；被拦截则保留选项供重试。取消不开始下载或打印。

## 接口、读取与完整性

wire v32 的 `POST /api/threads/{thread_id}/export-summary` 使用 exact JSON
`{scope: "all"|"last_turn"|"selected", turn_ids: string[], content: "qa"|"final_answers"|"prompts"}`；所有范围必须显式提供合法 content。
非 selected 的 turn_ids 必须为空数组；selected 必须 1..100 个唯一、非空、无首尾空白且最多 256 字符的 ID。拒绝未知字段与重复 ID。
POST 承载有界 ID 集合，仍是只读导出：无 writer／导航 intent，无 runtime mutation，
不续期会话，沿用同源、CSRF 和 document admission。旧 GET 不保留 alias。

`GET /api/threads/{thread_id}/export-turns` 只接受一个可选 exact `cursor`，返回
`FocusExportTurnPage {thread_id, turns, next_cursor}`；每个 `FocusExportTurn` 包含
`turn_id, prompt, answer, status`，摘要最多 160／240 字符，status 为
`completed|interrupted|failed|inProgress`。无下一页时 cursor 为 null。响应使用 no-store；
浏览器严格解码并校验目标线程。两条接口都经既有 staged document request 与
service-ingress boundary，固定 backend generation，读取在 RuntimeLoop 外执行，结算拒绝连接替换。

`WebThreadSummaryExportService` 是内容、目录读取与完整性 owner；
`thread_export_selection.py` 只拥有请求选择验证和纯问答提取规则。
只准入 exact direct、non-ephemeral、persisted-history 线程。全部问答／最终回复模式升序 summary 扫描；
最后一轮倒序定位，多选及全部 Prompt 升序核对目标。Prompt 导出不能只消费丢弃同轮补充的 summary。
paginated 线程通过 `thread/items/list(turnId=...)`
读取选中轮次的所有 item 页，只保留问答。legacy 线程用原 cursor 和页宽读取命中页的 full
items（每页最多 20 轮），不切换存储模式或读取 rollout 旁路。

单次请求总 deadline 为 30 秒；轮次扫描及各轮 item 扫描分别最多 100 页，paginated 每页
最多 100 条；最终 Markdown 最多 32 MiB。问答暂存也受 32 MiB 限制。协议解码器必须拒绝非对象 turn 与非法 cursor，不能过滤记录或把
异常 cursor 转为历史结束。拒绝错误身份、重复
item／turn 和不前进 cursor；任何错误都不返回 partial attachment。目录每次只读取一页。
“最后”以读取时上游可见历史为准，运行中新增提问可能在后续读取才可见。固定 ID 不等于上游原子快照；并发回滚导致目标消失时显式失败，不用邻近轮次替代。

Codex 依据为只读 checkout `2351d9e1b608e6f9d9a3699b71d7eb39ee41cfa4` 中
`app-server-protocol/src/protocol/v2/thread.rs` 的 `ThreadTurnsListParams`、
`ThreadItemsListParams`，`protocol/src/models.rs` 的 `MessagePhase`，以及
`app-server/src/request_processors/thread_processor.rs` 的 legacy/full 兼容路径（均相对 `codex-rs/`）。
不从源码推断部署版本：上游缺少接口时保留明确 unsupported 错误。

## 验证

覆盖三种范围 × 三种内容 × 两种历史模式、正文及标题的角色隔离、跨页同轮补充、勾选顺序、未完成和缺失轮次、legacy phase、分页边界、
连接替换及真实 adapter 解码的协议拒绝。浏览器验证宽／窄屏范围选择、跨页保留、取消清理、下载内容、
确认手势中的打印弹窗与独立预览；桌面窄屏模拟不替代移动端系统保存真机验证。
