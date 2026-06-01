# Thread Next-Load Settings 语义

英文原文：`docs/contracts/thread-next-load-settings-semantics.md`

本文定义当前项目仍然正式保留的 **thread-wise、持久化、在 next-load 生效**
的设置。

## 1. 当前范围

当前 thread-wise next-load state 只保留一个切片：

- **memory slice**
  - `memory mode`

也就是说，当前合同里已经**不再**包含：

- profile
- model
- model provider
- effort
- approval
- permissions
- collaboration mode

这些设置属于其他层级，见：

- startup profile：`docs/contracts/thread-profile-semantics.zh-CN.md`
- binding-wise next-turn：`docs/contracts/runtime-control-surface.zh-CN.md`

## 2. 基本事实

- memory mode 是 **thread-wise**，不是 binding-wise。
- 对 unloaded thread，持久化 memory mode 才是事实源。
- 对 loaded thread，事实源改由 live runtime 持有。
- 写入 thread-wise memory mode，不等于当前 live runtime 已立即改变。

当前受支持的恢复路径主要是：

- 飞书侧恢复 / 唤醒当前 thread
- 本地 `fcodex resume <thread>`

## 3. 写后持久源

正常 thread 上：

- 正式持久源是 `ThreadMemoryModeStore`

在 provisional 阶段：

- 若 thread 刚创建、尚未稳定 materialize，系统允许先记 pending seed
- 等对应 `turn/completed` 成功后再 promote 成正式 thread-wise 记录

## 4. 应用边界

memory mode 会在这些边界真正被消费：

- `thread/resume`
  - 对已存在 thread，按持久化 memory mode 恢复
- `thread/start`
  - 仅对“新建 thread 的 startup seed”路径注入

因此它的语义是：

- **next-load**
- 不是 turn-time override

## 5. 新建 thread 的 seed

实例可以配置 `new_thread_memory_mode_seed`。

这条 seed：

- 只影响新建 thread
- 不会改写其他已有 thread 的持久化 memory mode
- 新 thread 创建成功后，会再记录到该 thread 的正式/待提升 memory 状态里

## 6. 直接写入与 reset-backend

`/memory` 采用共享的 thread-wise 变更规则：

1. 若目标 thread 可验证为 globally unloaded
   - 允许直接写入
2. 若当前实例能通过 reset-backend 收口
   - 提供“应用并重置 backend”
3. 若不满足安全条件
   - fail-close

这里的“可写”判定只针对 thread-wise memory，不再附带 profile 语义。

## 7. 读侧视图

`/memory`、状态页和本地 thread 诊断面，应优先展示：

- 当前 thread 的持久化 memory mode

必要时可附带：

- 当前 live runtime 在本次 load 时观测到的 memory 配置
- 当前实例 `new_thread_memory_mode_seed`

但必须区分：

- “下次 load 会带什么”
- “当前 loaded runtime 正在用什么”

## 8. 非目标

本文不再承诺：

- thread-wise profile slice
- `fcodex -p/--profile` 改写 thread 的持久化恢复设置
- effort / model 等 turn-time 设置会因为写了 thread-wise state 而自动同步
