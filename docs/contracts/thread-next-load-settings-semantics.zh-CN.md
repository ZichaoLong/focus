# Thread Next-Load Settings 语义

英文原文：`docs/contracts/thread-next-load-settings-semantics.md`

本文定义一类共享合同：**thread-wise、持久化、在 next-load 生效的设置**。

它们共同构成一个 thread 的逻辑状态：

- **thread-wise next-load state**

当前这个状态里有两个切片：

- **profile slice**
  - `profile`
  - `model`
  - `model_provider`
- **memory slice**
  - `memory mode`

未来若还有新的 thread-wise 恢复设置，应默认复用本文，而不是再各自复制一套恢复/改写规则。

这里定义的合同，刻意比“所有可变 runtime 设置”更窄。

有些设置即使能在 loaded runtime 上被改变，也不代表它们属于
thread-wise next-load state。

与之相对的另一类是：

- **frontend-owned runtime settings**

例如，飞书前端可以把其中一部分 runtime settings 持久化在 binding 上；
而本地 `fcodex` / upstream TUI 也可以用另一套方式管理同类 runtime
settings。那种前端自有的持久化策略，不属于本文定义的
thread-wise next-load 合同。

关于“写时解析源 / 写后持久源 / 应用边界 / 读侧视图 / 生效判定 /
provisional 阶段”的统一分析框架，见：

- `docs/contracts/runtime-settings-fact-sources.zh-CN.md`

## 1. 基本事实

- 这类设置是 **thread-wise**，不是 binding-wise。
- 它们也不等同于 frontend-owned runtime settings。
- 它们对外承诺的是：在**受支持的恢复路径**上，同一个 thread 从 unloaded 恢复为 loaded 时，应使用同一份已持久化的 thread-wise next-load state。
- 对 **unloaded** thread，持久化的 next-load state 才是事实源。
- 它们**不是**当前 loaded runtime 的热更新真相。
- 对 **loaded** thread，事实源改由 live runtime 持有。

本文里的“受支持的恢复路径”，当前主要指：

- 飞书侧对当前 thread 的恢复 / resume
- 本地 `fcodex resume <thread>`

本文**不**承诺：

- 裸 `codex` 或其他合同外入口直接改动 runtime / config 后，本项目一定能自动统一这些分叉
- 已经 loaded 的 thread 会因为写入持久设置而立即热更新

## 2. 何时生效

这类设置在下列时机生效：

- 目标 thread 当前处于 backend `notLoaded`
- 随后通过受支持的恢复路径，把它恢复为 loaded

更准确地说：

- 这是 **next-load** 语义
- 不是“当前已 loaded 就地替换”语义

## 3. loaded snapshot 的观察边界

对 **loaded** thread，本项目当前只能稳定依赖一类观察值：

- `thread/start` / `thread/resume` 返回里的运行时字段

这里应把它理解为：

- **load-time observed snapshot**

它只回答：

- “这条 thread 在本次 load / resume 完成时，被观察到的运行时是什么？”

它不回答：

- “这条 loaded thread 在任意稍后时刻，完整的 live config 真相是什么？”

尤其不应把下面这些接口，当成 loaded live runtime 的完整权威读取：

- `thread/read`
  - 主要是线程元数据 / 历史读取
- `config/read`
  - 读取当前分层后的磁盘配置

当前项目合同里，load-time observed snapshot 已经足够支撑：

- unloaded -> loaded 恢复路径上的 thread-wise next-load 生效判断
- 对 loaded thread 的“本次载入时观测到什么”展示与诊断

但它**不**承诺：

- 对一个已 loaded thread，后续任意时刻都能重新精确读回 live runtime 的全量设置

## 4. 哪些正式入口会让 loaded runtime 偏离 snapshot

即使 thread 仍保持 loaded，upstream 也存在正式入口，会让后续实际行为偏离上面的
load-time observed snapshot。

当前至少应明确包括：

- `turn/start` 的运行时覆盖项
  - 例如 `model`、`cwd`、`approvalPolicy`、`sandbox` / experimental `permissions`
- `config/batchWrite` 且 `reloadUserConfig: true`
  - 会热重载 loaded threads
- `config/mcpServer/reload`
  - 会把 MCP 配置刷新排队到各 thread 的下一次 active turn

这意味着：

- 不同 TUI / 前端即使接在同一个 loaded thread 上，也可能通过正式上游入口改变它后续 turn 的实际运行行为
- 这种变化不需要依赖“手改快照文件”或“hack 进程内内存”

## 5. slice 改写语义

每个入口只负责自己那一块 slice：

- 显式 profile 改写，只负责 **profile slice**
- 显式 memory 改写，只负责 **memory slice**
- 纯 resume、没有显式改写请求时，不应改写任何 slice

对 profile 还要补一条硬约束：

- 只有 `profile`、`model`、`model_provider` 三项都齐全时，
 这份持久化 profile slice 才算有效
- 对于本项目的受支持路径，如果发现持久化 profile slice 不完整，
  必须 fail-close；不能偷偷拿当前本地配置或 backend 默认值把缺项补回来

对本地 `fcodex` 而言：

- 显式 `-p/--profile` 的语义是“主动改写 profile slice”
- 不带 `-p/--profile` 的语义是“不改写 profile slice，只按已持久化 slice 恢复”
- 某个 setting 目标值到底怎么解析，仍可由各自合同继续收紧；
  对 `feishu-codex` 的 profile 而言，这里明确优先 thread-stable，
  而不是按 cwd / project 动态变化

## 6. 何时允许直接改写

这类设置只有在 thread **verifiably globally unloaded** 时，才允许直接写入。

这要求至少同时满足：

- 当前 thread 没有 attached 的 Feishu binding
- 当前 thread 没有 live runtime lease
- backend 侧已确认该 thread 不在内存

所以：

- 单纯 `detached` 不够
- 只关掉一个飞书会话不够
- 本地 `fcodex` 仍开着时通常也不够

## 7. 不满足直接改写时怎么办

在进入 direct-write / reset-backend 判断之前，还应先应用一条幂等短路规则：

- 如果请求值已经等于当前 thread 的持久化设置，应直接成功返回
- 对 profile 而言，这里的相等判断覆盖完整的有效 next-load 设置：
  `profile`、`model`、`model_provider`
- 这属于 no-op success，不应再提示 reset-backend，更不应真的执行 reset

只有在“目标值与当前持久化值不同”时，才需要继续判断下面的 direct-write / reset-backend 路径。

因此：

1. no-op success
   - 目标值已等于当前持久化设置
2. 直接写入
   - 当前 thread 已 verifiably globally unloaded
3. 提供 “应用并重置 backend”
   - 当前 thread 还没满足直接写入条件，但当前实例可通过 reset-backend 收口
4. fail-closed
   - live runtime 由别的实例持有，或当前实例无法安全重置

无论是“直接写入”还是“reset 后写入”，真正被改写的都只是持久化的
thread-wise next-load state；它们不应被实现成对已 loaded runtime 的原地热改。

也就是说：

- 不要求用户先理解复杂的 detach / attach / unsubscribe 关系
- 应优先给出“直接写入”或“应用并重置 backend”的清晰路径

## 8. 与具体设置合同的关系

本文只定义共享规则，不定义各设置本身的业务语义。

具体含义仍分别由各自合同负责：

- thread-wise profile：`docs/contracts/thread-profile-semantics.zh-CN.md`
- thread-wise memory mode：`docs/contracts/thread-memory-semantics.zh-CN.md`
