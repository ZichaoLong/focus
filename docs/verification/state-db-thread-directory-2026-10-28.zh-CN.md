# 状态数据库会话目录验证（2026-10-28）

本记录只保存验证证据。目录策略由[技术设计的协议边界](../architecture/focus-design.zh-CN.md#23-协议边界)定义，
生命周期与历史编辑继续遵循现有合同。

## 范围与环境

源码起点为 Focus `cd599deb3576d3f26ef69c7f2e49b3a08f065424`。实现只在适配器的 `thread/list` 参数中加入
`useStateDbOnly=true`；现有过滤、分页、重复 ID 校验及 lifecycle RPC 保持不变。
在独立 worktree 中修改、构建和测试，未安装、发布或重启现有 Focus 实例，未移动或删除现有历史文件。

固定上游证据为 Codex 0.164.0
[`fe3b29455488c2e189e43ad5526a107900c5e1b7`](https://github.com/openai/codex/commit/fe3b29455488c2e189e43ad5526a107900c5e1b7)
的 `ThreadListParams.use_state_db_only` 与 rollout recorder 的数据库查询分支。
0.164.0 与 0.165.0 的实际二进制分别进行隔离 RPC 验证；没有把本地上游 checkout HEAD 当作发布版本的源码。
本地工具为 Python 3.11.15、Node 22.22.0、uv 0.8.14、系统 Chrome。

## 既有故障的只读验证

调查时，默认列表曾将同一 paginated thread 的两个 rollout 返回为相同 ID，导致 Focus 的严格解析失败。
旧 rollout 可能是当前线程和 fork 的 `history_base` 来源；删除任一文件不等于合法切换当前历史。

以修改后的适配器连接既有后端，只发送 initialize 与 `thread/list`、`thread/read`、`thread/turns/list`：

- 列表得到 9 条记录、9 个不同线程 ID。
- 目标线程的列表路径与 `thread/read` 选择的当前路径相同。
- 每页两轮、共四页，完整读取七轮历史，所有页面通过现有解析器。
- 没有向既有线程发送 resume、turn、fork、revert、archive 或 delete。

这是接口与历史读取证据，不代表已部署或完成生产 Web 验收。

## 隔离生命周期验证

分别使用独立临时 Codex home 和本地模拟 Responses SSE 服务。所有线程和 turn 均通过上游 RPC 创建，
不手工构造 rollout、不直接写数据库，也不请求外部模型。查询经过本次修改后的 Focus 适配器。
结束后停止临时进程并清理临时 home。下列场景在 0.164.0 和 0.165.0 均通过：

| 场景 | 观察与断言 |
| --- | --- |
| 全历史 fork、首轮之前的空 fork | 创建成功；空 fork 历史为空 |
| 未发送自身消息的 fork | 两类 fork 的 preview 均为空，数据库列表仍未包含它们 |
| 给两个 fork 各发送一条消息 | 来源与两个分支均能从数据库列表发现 |
| 来源回退到第二轮之前，再继续一轮 | 来源仍为同一 ID；列表仅一条，路径与 `thread/read` 一致，历史为两轮 |
| 已存在 fork 的历史 | 来源回退后仍保留原来的两轮及其自身一轮 |
| 搜索及每页一条的分页 | 过滤生效、cursor 结束、三个线程各出现一次 |
| 停止并重新启动临时 app-server | 三个已有消息的线程仍可发现 |
| 归档来源 | 从活动目录消失，在归档目录出现一次；分支的继承历史仍可读 |
| 取消归档 | 回到活动目录，从归档目录消失 |
| 来源仍被 fork 引用时删除来源 | 上游拒绝，列表与历史保持可用 |
| 先删除分支，再删除来源 | 操作成功，活动与归档目录均为空 |

隔离夹具的默认列表本次也返回三个不同 ID，未在该新建夹具中复现既有数据的重复枚举；
不将“每次 revert 都必然重复”作为结论。既有故障与生命周期兼容性分别由前述只读数据及隔离场景验证。

初次验证曾假设空 fork 会立即可见；实际结果否定了这个假设。未修改产品来补建索引，
保留[已有创建可见性提示](../contracts/thread-create-local-commit.zh-CN.md#创建后的列表观察与提示)。
`useStateDbOnly` 不修复所有上游可见性限制，也不承担手工导入或数据库修复职责。

## 本地门禁与导航闭环

| 门禁 | 状态 | 证据 |
| --- | --- | --- |
| 定向 Python 回归 | passed | 79 项；包括列表、generation、fork、历史编辑和目录生命周期动作 |
| 完整 Python 回归 | passed | 4,142 项 |
| 完整 Web 回归 | passed | 125 个文件、1,373 项，含 Chrome 浏览器用例 |
| Python 静态、import、依赖方向与 source-context | passed | ruff、compileall 及既有守卫；无新增豁免 |
| Web 依赖方向、类型、style、provenance、构建与 notices | passed | 既有 style 基线提示保持；固定 Kimi 来源验证通过 |
| 依赖锁 | passed | 使用固定 uv 0.8.14 重新解析，两份 lock 无差异 |
| 安装包构建 | passed | 两次独立构建的 ZIP 逐字节相同；仅验证，未发布或安装 |
| Web wire 与文档 | passed | 生成一致性、双语及索引检查 |

Web 初次运行未指定已安装的 Chrome，因此主动停止；指定 `FOCUS_TEST_CHROMIUM_EXECUTABLE` 后完整回归通过。
这不是产品代码失败。已有 source-context、style、依赖弃用与构建大小提示不改变通过结果。

按显式 changed paths 复核 catalog 与直接 imports/importers：没有新增 owner、public entry 或依赖方向，
已有 selector 可解析；未把缺少专门目录 capability 的索引当作权限或事实源，也未新增推测性的 capability。
已检查 `focus-web-mutations`、`focus-web-client-state` 的固定验证计划，其测试、sentinel 和 guard 由上述完整门禁覆盖。

适用远程工作流为 `CI` 与 `Docs`，须在推送后按精确提交 SHA 单独读回结果。
`Publish installable bundle` 仅支持显式手动触发，本任务不触发发布。
