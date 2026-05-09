# Thread Next-Load Settings 语义

英文原文：`docs/contracts/thread-next-load-settings-semantics.md`

本文定义一类共享合同：**thread-wise、持久化、在 next-load 生效的设置**。

当前属于这类设置的有：

- thread-wise profile
- thread-wise memory mode

未来若还有新的 thread-wise 恢复设置，应默认复用本文，而不是再各自复制一套恢复/改写规则。

## 1. 基本事实

- 这类设置是 **thread-wise**，不是 binding-wise。
- 它们对外承诺的是：在**受支持的恢复路径**上，同一个 thread 从 unloaded 恢复为 loaded 时，应使用同一份已持久化的设置。
- 它们**不是**当前 loaded runtime 的热更新真相。

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

## 3. 何时允许直接改写

这类设置只有在 thread **verifiably globally unloaded** 时，才允许直接写入。

这要求至少同时满足：

- 当前 thread 没有 attached 的 Feishu binding
- 当前 thread 没有 live runtime lease
- backend 侧已确认该 thread 不在内存

所以：

- 单纯 `detached` 不够
- 只关掉一个飞书会话不够
- 本地 `fcodex` 仍开着时通常也不够

## 4. 不满足直接改写时怎么办

如果还没满足直接改写条件，应按当前实例能力收口：

1. 直接写入
   - 当前 thread 已 verifiably globally unloaded
2. 提供 “应用并重置 backend”
   - 当前 thread 还没满足直接写入条件，但当前实例可通过 reset-backend 收口
3. fail-closed
   - live runtime 由别的实例持有，或当前实例无法安全重置

也就是说：

- 不要求用户先理解复杂的 detach / attach / unsubscribe 关系
- 应优先给出“直接写入”或“应用并重置 backend”的清晰路径

## 5. 与具体设置合同的关系

本文只定义共享规则，不定义各设置本身的业务语义。

具体含义仍分别由各自合同负责：

- thread-wise profile：`docs/contracts/thread-profile-semantics.zh-CN.md`
- thread-wise memory mode：`docs/contracts/thread-memory-semantics.zh-CN.md`
