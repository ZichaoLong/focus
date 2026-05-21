# Codex Goal 接入 Feishu 方案与实施计划 — 2026-05-21

Status: working material under `docs/_work/`. Not a repository fact.

## 1. 目的

本文把当前已经对齐的 `goal` 接入方案固化为仓库内工作文档，回答五个问题：

1. 上游 Codex 0.132.0 现在到底已经稳定提供了哪些 `goal` 能力
2. `feishu-codex` 应该依赖哪些上游事实，哪些不该复刻
3. 飞书侧 `/goal` 命令面和卡片面应该如何设计
4. 仓库里具体要改哪些模块
5. 这件事的验收标准是什么

本文是实施计划，不是正式产品合同。等代码落地后，相关结论需要下沉到：

- `docs/contracts/feishu-command-matrix*.md`
- `docs/contracts/runtime-control-surface*.md`
- `docs/architecture/feishu-codex-design*.md`

## 2. 当前上游事实

本次判断基于 2026-05-21 本地核对结果：

- 当前使用版本：`@openai/codex 0.132.0`
- 上游 `Goals` feature 已是 `Stable`
- `Goals` 默认开启，不依赖实验开关

当前 app-server 已提供以下 RPC / notification：

- `thread/goal/set`
- `thread/goal/get`
- `thread/goal/clear`
- `thread/goal/updated`
- `thread/goal/cleared`

当前 goal 数据形状至少包含：

- `threadId`
- `objective`
- `status`
- `tokenBudget`
- `tokensUsed`
- `timeUsedSeconds`
- `createdAt`
- `updatedAt`

当前 goal 状态枚举为：

- `active`
- `paused`
- `blocked`
- `usageLimited`
- `budgetLimited`
- `complete`

另外有两个重要边界：

- goal 只支持 materialized thread，不支持 ephemeral thread
- app-server 才是 goal 状态的事实源；TUI 只是其中一个前端

## 3. 不应复刻的上游部分

### 3.1 不复刻 TUI 交互形状

本项目不应把飞书侧做成 TUI 的镜像。

原因：

- TUI 有自己的 footer、弹出菜单、编辑态、局部刷新能力
- 飞书是 slash command + result card + callback action 的产品面
- 如果强行复刻 TUI 组合，后续会被上游 UI 调整反复牵动

因此，飞书只依赖 app-server RPC 语义，不依赖 TUI 文案、菜单顺序、隐藏交互或 footer 表达。

### 3.2 不本地维护一套 goal 状态机

本项目不应自建“goal 是否 blocked / done / completed”的本地判定器。

原则应固定为：

- 后端 goal 状态是唯一事实源
- 本地 runtime state 只保留 read-model / cache
- 不做本地自动续跑调度器
- 不做本地 goal 持久化副本

## 4. 飞书侧产品决策

### 4.1 命令面

第一阶段推荐正式支持：

- `/goal`
- `/goal show`
- `/goal set <objective>`
- `/goal clear`
- `/goal pause`
- `/goal resume`

推荐语义：

| 飞书命令 | 含义 | 上游 RPC |
| --- | --- | --- |
| `/goal` | 查看当前绑定 thread 的 goal 摘要 | `thread/goal/get` |
| `/goal show` | 同上；显式别名 | `thread/goal/get` |
| `/goal set <objective>` | 为当前绑定 thread 创建或覆盖 goal，并进入 `active` | `thread/goal/set` |
| `/goal pause` | 把当前 goal 状态切到 `paused` | `thread/goal/set` |
| `/goal resume` | 把当前 goal 状态切到 `active` | `thread/goal/set` |
| `/goal clear` | 清除当前绑定 thread 的 goal | `thread/goal/clear` |

第一阶段刻意不暴露以下 slash 子命令：

- `/goal edit`
- `/goal blocked`
- `/goal done`
- `/goal complete`
- `/goal budget ...`

原因：

- 这些能力虽然上游底层状态里存在，或未来可由 `thread/goal/set` 表达
- 但飞书第一阶段要优先保证稳定和可解释性
- 暂时不把“终态写入”与“预算写入”暴露给用户，可以避免产品面过早复杂化

### 4.2 状态展示面

第一阶段应增加一个单独的 thread-level `goal` 展示面，而不是把它塞进执行卡状态机。

建议展示内容：

- 当前 objective
- 当前 status
- `tokenBudget`
- `tokensUsed`
- `timeUsedSeconds`
- `updatedAt`

展示载体建议：

- `/goal` 返回单独的 goal 卡片
- `/status` 增加简短 goal 摘要行

可选动作按钮建议：

- `Pause`
- `Resume`
- `Clear`
- `Refresh`

第一阶段可以先做成简单 markdown card，不需要长驻卡，也不需要复杂 patch 生命周期。

### 4.3 与执行卡的关系

goal 可能跨多个 turn。

这在本项目中的含义必须固定为：

- 当前执行卡生命周期仍然是 turn-driven
- goal 运行期间，如果后端连续推进多个 turn，飞书侧仍会表现为多次“执行卡 -> 终态卡”
- goal 本身不是一张长生命周期执行卡
- goal 状态要通过独立的 thread-level 展示面表达

这是本次设计里最重要的边界之一；不能为了“看起来像一个长任务”而破坏现有 turn 卡片模型。

### 4.4 与 TUI 语义的关系

飞书侧允许定义自己的更稳定语义。

建议固定为：

- `/goal` 无参数等价于 `/goal show`
- `set/show/pause/resume/clear` 是飞书产品面定义
- 这不是“模拟 TUI 的 slash parser”
- 真正依赖的是 app-server 的 goal RPC

## 5. 仓库改造点

### 5.1 adapter / protocol 层

需要在适配层显式引入 goal 类型与方法。

建议新增：

- `ThreadGoalSummary` 数据类型
- `AgentAdapter.get_thread_goal(thread_id)`
- `AgentAdapter.set_thread_goal(thread_id, *, objective=None, status=None, token_budget=None)`
- `AgentAdapter.clear_thread_goal(thread_id)`

涉及文件：

- `bot/adapters/base.py`
- `bot/adapters/codex_app_server.py`

说明：

- `set` 要能支持“只改状态，不改 objective”的调用形状
- 当前 phase 1 不一定在飞书 UI 暴露 `token_budget`，但 adapter 层应保留字段，避免之后再破接口

### 5.2 runtime state / read model

当前 runtime state 还没有 goal 投影，需要补一个 thread-level read model。

建议新增 state 字段：

- `goal_objective`
- `goal_status`
- `goal_token_budget`
- `goal_tokens_used`
- `goal_time_used_seconds`
- `goal_created_at`
- `goal_updated_at`

建议新增 reducer message：

- `ThreadGoalStateChanged`
- `ThreadGoalCleared`

涉及文件：

- `bot/runtime_state.py`
- `bot/runtime_view.py`
- `bot/binding_runtime_manager.py`

边界：

- 这些字段只作为运行时投影，不需要写入 persisted binding store
- service 重启后允许这些字段先为空，等 `thread/goal/get` 或 notification 再恢复

### 5.3 adapter notification 路由

需要把 app-server goal 通知正式纳入通知解释层。

要接入：

- `thread/goal/updated`
- `thread/goal/cleared`

涉及文件：

- `bot/adapter_notification_controller.py`

目标：

- 订阅到目标 thread 的 binding 都能收到同一个 goal 投影更新
- goal 更新不应触发执行卡终态、补丁或退役逻辑
- 它应走独立的 thread-level 状态更新路径

### 5.4 Feishu 领域对象 / 命令路由

建议新增独立 domain，而不是把逻辑继续塞进 `CodexHandler` 或线程列表 domain。

建议新增：

- `bot/codex_goal_domain.py`

建议职责：

- 解析 `/goal` 子命令
- 调用 adapter goal RPC
- 生成 goal 卡片 / 文案
- 在本地 runtime state 中回填最新 goal 投影

路由接入点：

- `bot/codex_handler.py`

### 5.5 卡片与状态展示

建议新增：

- `build_goal_card(...)`

最低目标：

- `/goal` 命令返回单独 goal 卡
- `/status` 展示当前 thread goal 的摘要

涉及文件：

- `bot/cards.py`
- `bot/runtime_admin_controller.py`

第一阶段不要求：

- 常驻可 patch 的 goal 卡
- goal 触发全局消息刷新
- 把 goal 历史并入 execution transcript

### 5.6 `/help` 与正式合同跟进

在代码落地后，需要同步更新：

- `docs/contracts/feishu-command-matrix.md`
- `docs/contracts/feishu-command-matrix.zh-CN.md`
- `docs/contracts/runtime-control-surface.md`
- `docs/contracts/runtime-control-surface.zh-CN.md`
- `docs/architecture/feishu-codex-design.md`
- `docs/architecture/feishu-codex-design.zh-CN.md`

如果 `/help` 工作台决定纳入 `/goal`，还要同步更新：

- `bot/codex_help_domain.py`
- `docs/contracts/feishu-help-navigation*.md`

第一阶段也可以接受先只支持 slash 命令，不立即进入 `/help` 首页。

### 5.7 本地 `feishu-codexctl`

这是可选第二阶段，不是本次最小实现前提。

可选能力：

- `feishu-codexctl thread goal --thread-id <id>`
- `feishu-codexctl thread goal set --thread-id <id> --objective ...`
- `feishu-codexctl thread goal clear --thread-id <id>`

建议原因：

- 便于调试和运维
- 能在没有飞书交互的情况下直接核对 backend goal 状态

但如果实现顺序需要压缩，这一块可以晚于飞书命令面。

## 6. 推荐实施顺序

### Phase 1: 基础能力

- adapter goal RPC
- runtime state / runtime view goal 投影
- notification 路由

完成标准：

- 本地代码已经能读、写、清 goal
- 收到 `thread/goal/updated` / `cleared` 时，本地状态会更新

### Phase 2: 飞书命令面

- `/goal`
- `/goal show`
- `/goal set <objective>`
- `/goal pause`
- `/goal resume`
- `/goal clear`

完成标准：

- 用户可以在飞书中直接查看和控制当前 thread 的 goal
- 无需依赖 TUI 菜单语义

### Phase 3: 展示与合同

- `/status` goal 摘要
- goal 卡按钮
- help / contracts / architecture 文档同步

完成标准：

- 用户从 slash 命令、状态页、正式合同三处看到的是同一套语义

## 7. 测试与验收

至少应补以下测试：

- adapter 层 goal RPC 单测
- runtime state reducer 单测
- runtime view goal 投影单测
- notification controller 处理 `thread/goal/updated` / `cleared` 的单测
- `/goal` 命令解析与返回卡片单测
- `/status` 含 goal 摘要的单测

建议补的场景测试：

- 对已有 goal 的 thread 执行 `/resume` 后，goal 摘要能恢复
- goal 连续驱动多个 turn 时，现有执行卡生命周期不被破坏
- `paused` / `blocked` / `complete` / `budgetLimited` / `usageLimited` 能被正确展示

验收标准建议固定为：

1. 可以对当前绑定 thread 成功执行 `show / set / pause / resume / clear`
2. goal 更新不会污染 execution card 状态机
3. goal 跨多个 turn 时，执行卡仍按 turn 单位流转
4. `/status` 和 `/goal` 对同一 thread 展示一致
5. service 重启后，不会因为缺失本地 goal 持久化而产生错误状态；最多只是在重新读取前不显示摘要

## 8. 已确认的不做项

本次第一阶段明确不做：

- 复刻 TUI `/goal edit` 交互
- 暴露 `blocked / complete` 的用户写命令
- 做本地自动继续执行 scheduler
- 做长驻的 goal patch 卡
- 为 goal 新建独立持久化存储
- 让 goal 接管或替代现有 execution card 生命周期

## 9. 风险与后续观察点

当前主要风险不是上游“有没有接口”，而是产品面是否过度贴近 TUI。

需要继续观察的只有两类变化：

- app-server goal RPC / payload 是否发生破坏性变更
- 上游是否新增更稳定的 goal 管理 RPC，例如独立 budget 写接口或更清晰的 status mutation 约束

只要本项目继续坚持：

- app-server 为事实源
- 飞书命令面自定义且薄封装
- execution card 与 goal surface 分离

那么即使上游 TUI 变化较快，也不应对本项目造成高频重构。
