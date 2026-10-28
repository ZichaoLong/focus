# 历史 prompt 编辑与 fork 可见性验证（2026-10-28）

本记录是验证证据，不定义产品语义。正式合同见
[历史 prompt 编辑](../contracts/history-prompt-edit.zh-CN.md)、
[创建与本地提交](../contracts/thread-create-local-commit.zh-CN.md)。

## 环境与版本取证

源码起点为 Focus `af956bed411f08d98c79e9d2ecd68b077fddedf5`。
本次只修改、验证工作区源码，没有安装、发布、重启或升级现有 Focus/Codex 实例。

| 取证对象 | 实际版本或固定来源 | 使用范围 |
| --- | --- | --- |
| 当前安装的 Codex CLI | 0.165.0 | CLI 与实验 schema 导出 |
| default 正在运行的 app-server executable | 0.164.0 | 独立进程复用该二进制验证 |
| explorer 正在运行的 app-server executable | 0.165.0 | 独立进程复用该二进制验证 |
| 只读上游 checkout HEAD | `3f74ff28fa09530bd5bcfcbfcbb86553636dde94` | 不作为 0.164.0 的实现证据 |
| 固定 0.164.0 release 源码 | `fe3b29455488c2e189e43ad5526a107900c5e1b7` | TUI、fork/revert、goal 与历史实现审阅 |
| Focus schema 基线 | 由 0.147.0 更新到完整 0.164.0 experimental 导出 | 升级期 inventory/fingerprint 守卫 |

本地没有 0.165.0 release tag；其本次能力由真实二进制 schema 和 RPC 行为验证，
没有把 checkout HEAD 当作该 release 的源码。0.165.0 只验证本次协议子集。
本地验证工具为 Python 3.11.15、Node 25.9.0、系统 Google Chrome；浏览器通过 Playwright 驱动。

实际协议为 `thread/revert {threadId,beforeTurnId}`、`thread/reverted {threadId}` 与
`thread/fork.beforeTurnId`，两个版本均不再导出 `thread/rollback`。
initialize 的 `userAgent` 前缀来自 client name；版本判定使用其版本段，不能写死 `codex_cli_rs`。

## 第一阶段：fork 提示和告警

第一阶段独立验证通过后才接入历史编辑：后端 122 项、Web 169 项、类型检查、依赖方向和 source-context 守卫通过。
Chrome 中验证了分支提醒的 info 样式、完整中文文案、复制线程 ID 和“知道了”关闭操作。

后端只在创建成功后追加一次最多 2 秒的 `thread/list`，最多读一页 100 条；不追 cursor、不补持久索引。
命中时没有漏列提醒；一页未命中包括有 next cursor 的情况，都只描述“本次未在全局列表中找到”。
检查异常保留诊断和成功结果，命名失败同样保留已创建 ID，均不再次 fork。
浏览器按新分支 ID 保留提醒；期间切换线程不会在错误页面显示，切回才显示，关闭后不再出现。
内部技术告警和已恢复瞬时错误进入运行详情；操作失败/结果不明保留醒目提示和刷新或诊断入口。

## 第二阶段：实际二进制隔离验证

分别启动 0.164.0、0.165.0 的临时 app-server，使用独立临时 `CODEX_HOME` 与本地模拟 Responses SSE 服务。
通过官方 RPC 创建线程和真实 turn；没有对现有实例发送 mutation，也没有读取或改写 Codex 私有数据库。
结束后停止测试进程并删除临时 home。以下断言在两个版本均通过：

| 场景 | 实际结果 |
| --- | --- |
| fork 到首轮之前 | 新线程历史为空，来源完整 |
| fork 到较早轮及继承轮之前 | 排除目标轮及后续轮，来源历史不变 |
| 原生 revert | 返回相同 thread ID，收到 `thread/reverted`，历史在目标轮之前截断 |
| 先全量 fork，再 revert 来源 | 既有 fork 的继承历史不变 |
| 未发送新 prompt 的 fork | preview 为空，本次普通列表漏列 |
| 给该 fork 发送新 prompt | preview 填充，随后普通列表可见 |
| 活跃 goal 的编辑 fork | 不复制 goal、不产生自动 continuation |
| 活跃 goal 的原生 revert | 内部 reload 后未自动续跑；goal 持久状态仍为 active |

goal 回退检查在返回后继续观察 0.7 秒，并重新读取历史，未产生新 turn。
这结合固定 release 的内部 reload 源码证明本次回退路径，不承诺后续明确 resume/start 不续跑。
中断 mock provider 的在途请求时出现一次预期的 BrokenPipe；测试进程退出 0，全部断言通过。

Focus 后端测试另外覆盖：exact ID 参数、generation/version gate、首条用户输入分页读取、完整原文而非 preview、
同轮补充消息/图片/mention/text elements 的创建前拒绝、读取失败、cursor 不前进、来源不变、
foreign exclusive owner 拒绝、断线/错误 identity/internal error 的 unknown 结算、一次创建和通知失效缓存。

## 浏览器与自动回归

真实 FocusApp + HTTP/WebSocket mock 的 Chrome 用例覆盖：

- 将显示序号、行 ID 和截断文本故意设为不同于真实坐标/原文；请求仍携真实 turn/item，输入框恢复完整原文。
- 仅在用户修改并发送后提交一次 prompt；fork 成功本身不发送。
- fork 等待期间切到其他线程并输入草稿；回复不抢导航、不覆盖草稿，打开新分支才恢复。
- fork response 丢失时保留当前草稿、显示 unknown、不重复创建或发送。
- 分支提醒可复制 ID、关闭，无几秒自动消失；命名附注不变成创建错误。
- 重连遗漏回退通知时清除历史正文窗口、prompt 索引和详情读取；同 revision 的正常重连也重新加载正文。

浏览器测试使用独立 Vite cache 和固定语言，避免并行缓存与宿主语言影响测试定位。
首次合并测试暴露了默认语言不固定的问题：页面已正确显示中文“编辑并分叉”，测试却查找英文；
已固定测试 context 的语言并补充失败页诊断。此问题没有通过更改产品文案规避。

| 门禁 | 状态 | 证据 |
| --- | --- | --- |
| fcodex reviewed verification cone | passed | 283 项后端测试及方向/source-context 守卫 |
| Web reviewed verification cone | passed | 356 项后端、532 项 Web；最终完整 Web 回归包含后续重连缓存修复 |
| 完整 Web 回归、类型检查 | passed | 125 个测试文件、1,373 项测试，含 Chrome 交互；`vue-tsc --noEmit` |
| 完整 Python 回归 | passed | 本次变更隔离副本 4,140 项通过；含并发目录变更的工作区 4,148 项通过 |
| 0.164.0 schema drift、Web wire 生成一致性 | passed | 当前实际二进制导出与生成守卫 |
| Kimi provenance | passed | 固定 imported commit；仅更新修改摘要并登记新 Focus 测试 |
| Web 构建、notices、style 基线 | passed | 生产构建及 174 components / 88 license documents；17 条已有 style 提示，无新豁免 |
| 本次交付文档、导航影响及静态检查 | passed | 隔离本次交付文件检查通过；61 个 owned changed paths 可解析，无 stale selector；ruff、compileall、import/direction/source-context 通过 |
| 原工作区完整文档索引检查 | failed | 任务开始前已有的未跟踪 daemon migration 报告缺两个 index 链接；未改动该报告或替其登记 |
| 手动原生 TUI 双 Esc 编辑 | not-run | 没有对现有 fcodex 会话执行；以原生 RPC/proxy 测试及固定 TUI 源码审阅为证据 |
| 发布、安装、现有实例更新、远程 CI | not-run | 本次未请求，留待独立步骤 |

本次完整 Python 初跑检出四处本次变更造成的不一致：wire 版本断言、TypeScript enum 类型引用、
以及两项测试共用的 adapter stub 缺单页列表端口。修正后 20 项定向回归通过，再执行完整回归。
Node 本地存储、Python 上游依赖弃用、故意构造重复 ZIP 条目和 Vite 大 chunk 提示均未改变门禁结果。

常规复核入口（Python/Node 路径按环境显式传给 verifier）：

```bash
python scripts/focus_verify.py fcodex-runtime
python scripts/focus_verify.py focus-web-mutations focus-web-client-state focus-web-history-navigation
python -m pytest -q
# 在 web/ 下执行 npm test、npm run typecheck、npm run build。
python scripts/generate_focus_web_wire.py --check
python scripts/check_codex_app_server_drift.py --schema-dir <0.164.0-experimental-schema>
bash scripts/check-docs.sh
```

收尾期间曾出现另一项并发目录变更：adapter 的 paginated rollout 去重、`test_codex_app_server_inventory.py`
以及 Web wire 合同的对应目录段落。本任务没有修改或回退该工作；为排除其影响，在临时源码副本中仅保留
本次 `fork_thread` 适配后复核。最终检查时并发 diff 已从共享工作区消失，本次 61 个 owned 文件与验证副本一致。
复用既有依赖供测试，没有安装或修改运行实例。

## Schema 审阅与导航闭环

0.164.0 inventory 变动已明确分类：新增 `thread/revert` 纳入既有 mutation owner；原有 `thread/fork`
由过时的 denied 分类改为已实现的 mutation；移除上游已删除的 `thread/rollback` 条目。
新增 `thread/reverted` 纳入历史失效 consumer，fork/revert/items-list response roots 纳入指纹。
新增 attachment、queue、timeline、sample、prediction、items/read、readState、turn/settings 等线程能力明确拒绝；
其余新增 account/project/plugin 等全局方法继续走不可变 default-deny，没有扩大 fcodex allowlist。
新增 `functionCallOutput` item 标记 unsupported。其他新增通知仅记录 inventory，没有引入消费者。
可达 schema 的新字段与 enum 更新指纹；不因此宣称 Focus 已使用所有上游能力。

沿既有 `focus-web-mutations`、`focus-web-client-state`、`focus-web-history-navigation`、`fcodex-runtime`
能力复核 owner、合同和测试引用，没有创建新 runtime/history owner。显式 61 个 owned changed paths 中，
35 个有可解析的 catalog 命中；其余 26 个为生成物、英文同步稿、呈现组件、locale、测试 fixture 或相邻类型等直接依赖，
已人工复核，不因 unmapped 新增推测性 owner。跨模块 consumer 由完整 Python/Web 回归覆盖。

## 剩余边界

- Web 仅支持 paginated 历史每轮首条完整纯文本 prompt，最大 UTF-8 1 MiB；附件、结构化 text elements 与同轮补充消息明确拒绝。
- 原生 revert 也只支持持久 paginated 历史；原生 TUI 的图片、mention 等恢复由对应版本 TUI 拥有，已审阅源码，未做手动附件编辑烟测。
- 原生 revert 可中断另一前端正在运行的普通 turn，不回滚文件，不取消 goal；foreign exclusive/autonomous lease 仍由现有 owner 拒绝。
- 尚未恢复到 Composer 的原文 handoff 只保存在当前 document 内存，F5 后不保证保留；恢复后的草稿使用现有 Composer 存储。
- 不保证关闭或重启后自动发现所有空 preview 分支。用户应按提醒保存 ID，手动重新打开。
- 编辑 fork 只放行已核实的 0.164.0/0.165.0；未知版本拒绝发送，不退化为全历史 fork。
