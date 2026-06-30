# Shared Backend 与 Resume 安全性

英文原文：`docs/decisions/shared-backend-resume-safety.md`

另见：

- `docs/architecture/focus-shared-backend-runtime.zh-CN.md`：当前 shared backend 与 wrapper 的运行时模型
- `docs/contracts/runtime-control-surface.zh-CN.md`：`/status`、`/detach` 与本地管理面的共享状态词汇
- `docs/contracts/thread-profile-semantics.zh-CN.md`：精确的命令与 wrapper 语义
- `docs/architecture/focus-design.zh-CN.md`：架构与仓库边界

## 1. 上游基线

- 上游项目：[`openai/codex`](https://github.com/openai/codex.git)
- 当前本地验证基线：`codex-cli 0.118.0`，本地可解析到上游 tag
  `rust-v0.118.0`（commit
  `b630ce9a4e754d35a1f33e4366ba638d18626142`），核对日期为 2026-04-03
- 如果本文后续需要引用具体上游源码位置，应优先使用绑定到该基线
  commit 的 `openai/codex` permalink，而不是开发者本机 checkout 路径
- 本文只聚焦安全边界与 `/resume` 语义；wrapper 运行时细节不再在这里重复展开，而是以 `focus-shared-backend-runtime` 为准。

## 2. 问题陈述

只有当两个前端通过同一个 app-server backend 写入同一个线程时，它们才是安全的。

如果它们通过不同的 app-server 进程去恢复同一个持久化线程，就可能各自物化出自己的 live 内存线程，随后再追加彼此冲突的状态。

多实例支持落地后，这条规则需要更明确地读成：

- 多个实例可以共享 `CODEX_HOME` 和 persisted thread namespace
- 但同一时刻，一个 thread 只能被**一个实例 backend** 持有 live runtime
- 裸 `codex` 自己开的 isolated backend 仍然完全不在这条协调路径内

本文定义当前的安全模型，用于说明：

- shared backend 路径
- 对当前 backend 中未加载线程执行 `/resume`
- 同一线程在多个飞书会话中的行为边界

## 3. 已验证约束

### 3.1 我们可以依赖的硬事实

- 在同一个 app-server 进程内，恢复一个已经加载的线程时，会复用已加载线程和订阅者模型，而不是创建第二份 live 副本。
- `thread/loaded/list`、`thread/list.status` 和 `thread/read.status` 只描述当前 app-server 进程。
- `thread/read` 读取的是已存储历史，不会创建 live thread。
- `thread/resume` 会把线程加载进当前 app-server，成为 live thread。

### 3.2 我们不能依赖的事实

- 我们无法可靠检测另一个 stock TUI 进程当前是否正在写同一个线程。
- `source` 和 `service_name` 只是来源提示，不是 live ownership 或 lock 信号。
- 我们无法强制另一个 stock TUI 进程停止写入。
- 以当前公开机制，我们无法自动附着到原生 TUI 自带的 app-server。

## 4. 核心安全规则

所有地方统一使用一条规则：

- 一个线程应只通过一个 backend 写入。

如果用户希望飞书和本地 TUI 安全地同时操作同一个 live thread，它们就必须连接到同一个 app-server backend。

在当前仓库里，这条规则又拆成两层：

- **实例内**：Feishu 与 `focus` / `fcodex` 可以安全共享同一个实例 backend
- **实例间**：通过机器级 `ThreadRuntimeLease` 保证同一 thread 不会被两个实例 backend 同时 live attach

## 5. Backend 安全边界

### 5.1 实例内 shared backend

这是推荐的安全路径。

特性：

- 飞书与本地 TUI 通过同一个 app-server backend 写入
- 已加载线程状态在这个 backend 内共享
- 多个本地 TUI 窗口附着到同一个 backend，也不会引入跨进程分叉

shared backend 与 `focus` / `fcodex` wrapper 具体如何实现，见 `docs/architecture/focus-shared-backend-runtime.zh-CN.md`。

### 5.2 另一个 FOCUS 实例 backend

这是多实例模式新增的一条边界。

特性：

- 多个实例共享 persisted thread namespace
- 但每个实例有自己独立的 live backend
- 跨实例 `attach / continue` 前，会先检查是否仍有其他运行中的实例把该
  thread 报告为 `loaded`
- loaded gate 通过后，仍需原子 claim 机器级 `ThreadRuntimeLease`，以防多个
  实例几乎同时 cold resume 的竞态
- 只要另一实例仍持有 loaded runtime，或 loaded 事实无法被安全验证，就必须
  明确拒绝，而不是尝试强行夺走这份 live runtime

因此，这不是“共享 backend”，也不是“可以并发双写的两个 backend”。
它是一条**共享持久化 namespace、但 live runtime 严格单 owner** 的协调路径。

### 5.3 裸 `codex` 的 isolated backend

当用户脱离 shared backend 直接运行 stock TUI 时，就是这一路径。

特性：

- FOCUS 无法知道这个本地 TUI 是空闲、关闭，还是即将写入
- FOCUS 不能安全地假设自己对该线程拥有独占所有权
- 如果要在本地继续同一个 live thread，应改用 `focus` / `fcodex` 走同一个实例的 shared backend
- 如果仍用裸 `codex` 在另一个 backend 写同一线程，就超出了当前支持的安全路径

## 6. `/resume` 安全模型

### 6.1 分类

在匹配到目标线程后，只使用硬事实进行分类：

1. `loaded-in-current-backend`
2. `not-loaded-in-current-backend`

不要再额外发明一个基于启发式缓存的“可能安全”类别。

### 6.2 已加载于当前 backend

如果目标线程已经加载在当前 FOCUS backend 中：

- 直接恢复
- 将当前飞书会话绑定到该线程
- 不展示风险卡片
- `resume` 不会借机改写这个 live runtime 的 profile 或 provider

这是安全的，因为该线程已经活在同一个 backend 里。
`resume` 本身不会把这条已加载线程再按额外的项目自管
profile/provider slice 重解释一次。

### 6.3 未加载于当前 backend

如果目标线程当前没有加载在本 backend 中，本仓库的安全取舍是直接调用 `thread/resume`。

行为：

- 直接恢复目标线程
- 将当前飞书会话绑定到该线程
- 如果用户随后通过 `focus` / `fcodex` 接入同一个实例 shared backend，则飞书与 `focus` / `fcodex` 可以继续安全地共同读写这个 live thread
- 若另一运行中实例仍把该 thread 保持为 loaded，则 loaded gate 按
  fail-close 直接拒绝
- 若 loaded gate 已通过，但另一实例先一步赢得了原子 lease claim，则当前
  写入仍按 fail-close 拒绝，并把操作者引回 owner 实例或 `reset-backend`
- `resume` 不会回放任何额外的项目自管 thread-wise
  profile/memory/provider slice

这条路径的前提是：

- 本地继续同一线程时，使用 `focus` / `fcodex`
- 不要再用裸 `codex` 通过另一个 backend 写这个线程

这里需要刻意记住一件事：两端现在共享的是一套**更窄**的 resume 语义，而不是旧的 profile-restore 模型。

- 飞书与 `focus` / `fcodex` 都不会在 resume 时回放项目自管的 thread-level
  profile/memory slice
- backend 启动基线来自当前实际运行的实例 backend
- turn-time override 仍是 frontend-owned，而不是 thread-owned
- 飞书侧仍可能为了紧随其后的 turn 准入，额外携带 binding 级 admission 设置；但那不会产生 thread 级持久化 truth

这里还需要明确记录一条当前实现细节：普通的 unloaded-thread `/resume`
仍然是直接恢复；但当目标是 unloaded 且 persisted `goal=active` 时，当前
UI 不再把它当成普通 direct resume，而是展示确认卡，因为这里实际上存在两种
语义明显不同的路径：

- `直接恢复`
  - 直接调用 `thread/resume`
  - 然后再用 `thread/settings/update` 补齐 loaded-thread 设置
  - 如果 app-server 立刻自动续跑 active goal，那么第一轮 autonomous goal turn
    只保证沿用 backend 当时已经生效的 loaded-thread 设置
- `按当前设置恢复并保持 paused`
  - 先把 persisted goal 暂停
  - 再 cold-resume 该 thread，并携带上游 `thread/resume` 支持的那一小段
    resume-time override
  - 然后排队做 loaded-thread 设置同步
  - 但 goal 保持 `paused`，而不是自动恢复

因此，对“可能同时被另一个 isolated backend 写入”的线程，避免双 backend
写入的责任仍主要在操作侧，而不是靠大范围 UI 强制保护。

多实例模式不再额外引入一层 thread admission 过滤：

- 所有实例都从同一套共享 persisted thread 命名空间解析目标
- 飞书 `/threads` 与 `focusctl thread list --scope cwd` 都是在这套命名空间上的当前目录视图
- 但一旦真的要 live attach，所有路径仍统一服从 `ThreadRuntimeLease`

### 6.4 当前命令状态矩阵

当前仓库里，`/resume` 与 `/goal resume` 的行为取决于 4 条状态轴：

1. 目标 thread 是否已加载在当前 backend
2. 上游 goals feature 是否启用
3. persisted goal 当前状态
4. 当前飞书 binding 是 `attached` 还是 `detached`

这里最关键的区分是：

- `cold overrides`
  - 通过 `thread/resume` 直接携带的字段
  - 当前只有：`model`、`approval_policy`、`permissions_profile_id`、
    `reasoning_effort`
- `queued loaded-thread sync`
  - 通过 `thread/settings/update` 同步的字段
  - 用于 loaded-thread resume 之后；上游只保证“已入队”，不保证调用返回时就已生效

#### `/resume`

| 前置状态 | UI 路径 | 实际顺序 | 是否会自动继续 goal | 第一轮 resumed goal turn 前能保证的设置 |
| --- | --- | --- | --- | --- |
| loaded，任意 goal 状态 | 无确认 | `thread/resume -> bind -> thread/settings/update` | wrapper 不额外触发继续 | 除 backend 当前已加载事实外，没有额外严格保证；sync 只是排队 |
| unloaded，goals disabled | 无确认 | `thread/resume(cold overrides) -> bind -> thread/settings/update` | 没有 goal 路径可继续 | 只有 cold overrides |
| unloaded，没有 goal | 无确认 | `thread/resume(cold overrides) -> bind -> thread/settings/update` | 不会 | 只有 cold overrides |
| unloaded，goal paused | 无确认 | `thread/resume(cold overrides) -> bind -> thread/settings/update` | 不会；goal 保持 paused | 只有 cold overrides |
| unloaded，goal active，直接恢复 | 确认卡：直接恢复 | `thread/resume -> bind -> thread/settings/update` | app-server 可能立刻继续 | wrapper 不保证当前 binding 设置一定先赢得时序 |
| unloaded，goal active，保持 paused | 确认卡：保持 paused | `thread/goal/set(paused) -> thread/resume(cold overrides) -> bind -> thread/settings/update` | 不会；goal 保持 paused | 只有 cold overrides |

#### `/goal resume`

| 前置状态 | 实际顺序 | 真正触发继续执行的点 | continuation 前能保证的设置 |
| --- | --- | --- | --- |
| 当前没有绑定 thread | fail closed | 无 | n/a |
| goals disabled | fail closed | 无 | n/a |
| 当前 thread 没有 goal | fail closed | 无 | n/a |
| loaded，goal paused | `thread/settings/update -> thread/goal/set(active)` | 最后的 `set(active)` | 除已加载 backend 当前事实外，没有额外严格保证；sync 只是排队 |
| loaded，goal active | `thread/settings/update` | 无新增触发；backend 保持当前状态 | 除已加载 backend 当前事实外，没有额外严格保证；sync 只是排队 |
| unloaded，goal paused | `thread/resume(cold overrides) -> [按需 bind] -> thread/settings/update -> thread/goal/set(active)` | 最后的 `set(active)` | 只有 cold overrides |
| unloaded，goal active | `thread/goal/set(paused) -> thread/resume(cold overrides) -> [按需 bind] -> thread/settings/update -> thread/goal/set(active)` | 最后的 `set(active)` | 只有 cold overrides |

当前回滚范围也需要明确：

- 如果 pause-first 的恢复路径在暂停 goal 之后失败，wrapper 会尝试把
  `goal=active` 恢复回去
- 但不会回滚已经 materialize 出来的 `thread/resume`
- 不会撤销已经入队的 `thread/settings/update`
- 也不会清掉已经重新绑定的 Feishu binding

### 6.5 Attach 与 loaded 的关系

`binding attached` 和 `backend loaded` 仍然是两条独立状态轴。

它们相关，但不等价：

- `attached`
  - 表示当前 Feishu binding 在服务拥有 live subscription 路径时，应接收这个
    thread 的实时事件
- `loaded`
  - 表示该 thread 当前在 app-server 里具有 runtime residency

所以正式模型仍然是正交轴，而不是“只要 attached 就永远 loaded”。

为什么仍可能出现 `attached + unloaded` 这类前置状态：

- 上游可以独立于本地 bookmark 把 backend thread unload 或 close 掉
- wrapper 会刻意保留逻辑上的 binding bookmark，而不是清空当前会话的
  current thread
- `thread/closed` 只会收敛执行态，不会抹掉 binding bookmark，也不会强制清空
  用户看到的 attach/detach 意图

但还要补一条当前实现语义：显式 `attach` 操作并不是一个纯 flag flip，而是一个
组合操作：

- control-plane attach 会先调用 `thread/resume`
- 然后再把 Feishu chat re-bind 到这条 live thread

因此：

- 一次显式 `attach` 成功返回后，这个 thread 在“那一刻”应当是 loaded 的
- 但 `attached` 仍不代表 backend 之后永远不会再次 unload

## 7. 来源展示与对称风险

把来源元数据只作为信息展示：

- `source`
- 如果存在则展示 `service_name`

用途：

- 帮助用户理解线程来自哪里
- 帮助区分 shared thread 与 external thread

不要仅凭 provenance 自动做安全决策。

风险是对称的：

- 如果飞书把外部线程恢复进自己的 backend，可能产生分叉
- 如果用户之后又用裸 `codex` 在另一个 backend 恢复飞书正在使用的线程，同样存在风险

FOCUS 不能消除这种风险。本仓库选择了更直接的 `/resume` 路径，因此安全边界依赖一条操作约束：需要多端继续同一 live thread 时，统一走 shared backend / `focus` / `fcodex`，不要混用裸 `codex`。

## 8. 飞书多会话边界

安全性和 UX 是两个不同问题。

### 8.1 安全性

同一个实例下的所有飞书会话本来就共享同一个 backend 进程，因此不会像飞书和裸 TUI 之间那样，为每个会话创建不同的 app-server 进程。

所以它们不会遭遇那种跨进程双 live thread 分叉问题。

### 8.2 当前 UX / ownership 取舍

当前模型已经不是“每个 `thread_id` 只维护一个主要通知绑定”的旧模型。

现在更准确的描述是：

- 同一个 `thread_id` 可以同时存在多个 Feishu subscriber / binding
- 这些 subscriber 共享同一个 backend thread，因此对 backend 安全
- 但真正驱动执行与交互路由的仍是 owner / lease，而不是“最后一个绑定者”

具体来说：

- 同实例 Feishu / `focus` / `fcodex` 的写入准入与审批、补充输入、中断等交互准入，统一由当前实例内的 `interaction owner` 控制
- 当某线程当前没有显式 owner，但只有一个 Feishu subscriber 时，运行时可以按“唯一 subscriber”补位路由；一旦出现多个 subscriber，就必须依赖明确 owner，而不再靠“最后一个绑定”猜测

这带来的用户侧结论是：

- 非 owner 的 Feishu 会话仍可以保留 binding，并继续观察线程的共享事实状态
- 已订阅该 thread 的 Feishu 会话会收到普通执行流、终态执行卡和终态结果载体
- 非 owner 不能继续写入，也不能处理当前 turn 的审批 / 输入 / 中断请求
- 当前不承诺“多个飞书会话都看到完全镜像的可交互 live UI”；审批卡和 request 驱动交互事件仍只路由给当前 `interaction owner`

因此，这一层的决策结论是：

- 飞书内部允许多 subscriber，共享同一 backend thread
- 可写性与可交互性由 owner lease 决定
- 普通回复与终态输出按 subscriber 广播，交互请求按 owner 路由

## 9. 相关文档

- `docs/contracts/thread-profile-semantics.zh-CN.md`：`/threads`、`/resume`、`focus` / `fcodex` 与 profile 的精确命令语义
- `docs/architecture/focus-shared-backend-runtime.zh-CN.md`：shared backend、动态端口发现、cwd 代理与 wrapper 运行时行为
- `docs/architecture/focus-design.zh-CN.md`：架构、设计约束与当前仓库结构
