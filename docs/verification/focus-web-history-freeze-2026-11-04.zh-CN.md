# Focus Web 旧历史卡死定位与修复（2026-11-04）

## 根因

多个已挂载用户消息缺少 `promptTiming.submittedAtMs` 时，`PromptTime.vue`
的 computed 会通过 `promptTimingPresentation.ts` 查询本地时间记录。
`createPromptTimingStore.local()` 在查询中调用 `merge()`，后者每次都为
`records.value` 创建新数组，即使结果仍为空或内容完全相同。多个时间组件
因此反复使彼此的 computed 失效，Vue 更新队列持续执行，占住浏览器主线程。

引入回归的提交是 `05d1b857d1783b4394be3c983744abe54dfcd6a9`
（2026-10-30，`feat: unify Focus data retention and cleanup`）：

```diff
- local(id: string) { return records.value.find(row => row.submission_id === id); },
+ local(id: string) { merge(); return records.value.find(row => row.submission_id === id); },
```

独立浏览器在用户报告的旧会话中复现了两个卡死目标。其中一个正文请求已返回
HTTP 200、40,604 字节、30 个展示行；窗口包含两条有原生输入时间和提交编号、
但没有 `promptTiming` 的用户消息。4.70 秒 CPU profile 与暂停栈指向 Vue 更新
队列、时间记录读取和重复渲染。

## 隔离验证

清空测试浏览器的提交时间记录，只保留真实响应中的用户消息，得到：

| 浏览器临时实验 | 结果 |
| --- | --- |
| 仅一条缺少行内提交时间的用户消息 | 正常响应 |
| 两条均缺少行内提交时间的用户消息 | 主线程求值等待 2.5 秒仍无响应 |
| 两条消息均提供测试用行内提交时间 | 正常响应 |
| 两条旧消息不变，仅使 `local()` 恢复纯读取 | 正常响应 |

实验无需回复正文、图片或工具内容。测试用时间与 JavaScript 响应拦截只存在于
测试浏览器，没有写入服务器。临时恢复纯读取后，首批目录中的 23 个 Prompt
均可正常访问，未记录页面错误。故障取决于当前挂载消息的时间回退组合，不绑定
特定线程；向上翻和点击 Prompt 都可能挂载多个这样的时间组件。

## 实现与回归

- `promptTimingStore.ts` 的 `local()` 改为纯读取，在返回结果时检查保留期及
  `activeTimingIds`，不重新读取存储、合并或发布响应式状态。
- 提交与同步入口继续执行既有合并、过期过滤和跨标签页版本选择，避免旧内存
  快照重新保存或同步过期记录。
- `PromptTime.vue` 跳过无提交编号的本地记录查询，保留原生输入时间回退。
- 中英文提交时间合同明确查询无副作用，状态变更由提交、同步等入口执行。

新增回归覆盖：

1. 两次缺失记录查询不得通知其他响应式读取者；旧实现对此测试失败。
2. 缩短保留期后查询隐藏过期记录，后续同步与提交不重新保存过期项。
3. 提交跨越过期边界时，在途记录仍可读取且受清理保护；结算后按期淘汰。
4. 使用真实页面与时间 store，在 1280px 和 390px 下分别点击旧 Prompt、向上
   翻页，加载两条缺少提交时间的旧消息；验证时间详情点击、滚动、切回最新
   Prompt、按需诊断请求及输入草稿保留。还原旧 store 后，这条浏览器回归因
   `Maximum recursive updates exceeded in component <FocusPromptTimingHistory>` 失败。

浏览器回归的 API 响应均为合成数据，不携用户真实会话内容。既有回归继续覆盖
跨标签页完成记录合并、同步竞争、存储失败与提交语义。

## 本地验证结果

环境为 Linux、Python 3.11.15、Node.js 22.22.0，浏览器回归使用本机 Chromium。

| 门禁 | 结果 |
| --- | --- |
| 全量 Python 测试 | passed：4229 项 |
| 全量前端测试 | passed：131 个文件、1438 项，含四种旧历史浏览场景 |
| Python lock、lint、编译、源码约束、依赖方向、循环依赖、wire 与文档检查 | passed；lock 无差异 |
| 前端类型、依赖方向、样式基线、Kimi provenance、生产构建与第三方 notices | passed |
| 安装包构建与校验 | passed：两次生成的 ZIP 字节一致，仅验证，未安装 |

上述全量测试覆盖本次 reviewed capability 的 focused tests、sentinels 与所需
更宽验证锥。远端工作流结果另随最终提交汇报，不以本地通过推定远端成功。

## 导航与交付范围

修复范围为 `focus-web-prompt-timing` 及其数据保留期直接依赖；正文分页和
滚动 owner 无语义变更。相关合同为 `focus-web-prompt-timing` 和 `data-retention`。
既有 capability 的入口、owner、合同位置及测试文件继续有效，无失效引用或
测试拓扑变更，无需修改 catalog。

本次执行仅修改、验证并提交仓库内容。构建产物仅用于本地验证，不安装、不发布，
不更新或重启运行中的 Focus；运行态更新由用户稍后在浏览器执行。
