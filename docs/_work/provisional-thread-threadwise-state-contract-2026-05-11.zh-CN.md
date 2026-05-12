# provisional thread 与 thread-wise persist state 合同

日期：2026-05-12

## 1. 目的

本文记录 `feishu-codex` 在本地 `fcodex` 路径下，围绕：

- `profile`
- `memory`
- provisional thread
- creation-time seed

的**当前合同**。

这里的重点不是泛泛讨论“thread-wise 配置应该是什么”，而是明确：

- `fcodex` 启动后，新线程 seed 在什么阶段属于谁
- 什么时候允许把它视为正式 thread-wise persist state
- 顺序第二次 `thread/start` 和少见的并发 `thread/start` 应该怎么处理
- websocket 断连 / 重连后，这份 seed 应该如何延续

## 2. 适用范围

本文描述的是：

- 本地 `fcodex` wrapper
- 它拉起的本地 websocket proxy
- proxy 与 shared app-server 之间的 `thread/start` / `thread/resume` 生命周期

本文**不等于**整个 `feishu-codex` 系统所有入口都已经完全统一成这一合同。

特别是：

- 飞书侧 binding continuity
- 本地 `feishu-codexctl` 对 explicit `thread_id` 的控制面语义

仍属于更大范围的系统合同，不在本文这次落地范围内。

## 3. 核心判断

### 3.1 `profile` / `memory` 是 thread-owned next-load state

对 `feishu-codex` 来说：

- `profile`
- `memory`

都应被视为 thread-owned 的 next-load state，而不是“当前 frontend 的临时启动参数”。

也就是说，用户真正要的是：

- 同一个 thread 下次再 load 时，继续沿用同一份设置
- 这份设置不跟着本地当前 cwd 漂移
- 也不跟着当前 frontend 漂移

### 3.2 只有 materialized logical thread 才拥有正式 persist state

虽然 upstream `thread/start` 很早就会返回一个 `thread_id`，但：

- 拿到 provisional shell 的 `thread_id`

不等于：

- 拿到了正式的、可持久化的 materialized logical thread

因此正式的 thread-wise persist state 只属于：

- materialized logical thread

而不属于：

- 尚未 materialize 的 provisional shell

## 4. 三段状态机

本地 `fcodex` 的 creation-time seed 在合同上分三段：

### 4.1 `unbound launch seed`

这是 `fcodex` 启动后、首个成功 `thread/start` 响应回来之前的状态。

此时：

- seed 还没有绑定 `thread_id`
- 它只属于当前 `fcodex` proxy 会话
- 它不是某条 websocket 连接私有的状态

这份 seed 目前由 proxy 进程级共享状态持有，而不是挂在某个单独 gate 上。

如果连接在这个阶段关闭，还要继续区分两种子情况：

- `thread/start` 明确失败或明确没有拿到有效 `thread_id`
- `thread/start` 是否已被 backend 接收、但本地在断连前没观察到结果

前者可以安全释放 seed；
后者属于 outcome unknown，当前合同按 fail-close 处理。

### 4.2 `pending threadwise seed`

当某个 `thread/start` 成功返回并带回 `thread_id` 后：

- launch seed 会绑定到这个 `thread_id`
- 但仍然只是 pending
- 还不是正式 thread-wise persist state

此时它的语义是：

- “如果这个 provisional thread 后续成功 materialize，就把这份 seed promote 成正式 thread-wise state”

而不是：

- “这个 provisional shell 现在已经正式拥有 persist state”

### 4.3 `promoted thread-wise state`

当该 thread 的第一个用户 turn 成功完成时：

- 收到 `turn/completed`
- `turn.status == completed`
- 且没有 turn error

这份 pending seed 才允许 promote 为正式的 thread-wise persist state。

promote 后才会真正写入：

1. thread-wise profile store
   - `profile`
   - `model`
   - `model_provider`

2. thread-wise memory store
   - `off`
   - `read`
   - `read_write`

## 5. 顺序与并发合同

### 5.1 顺序第二次 `thread/start`

这是常见用户路径，必须稳定支持。

例子：

1. 用户启动 `fcodex`
2. 首个 `thread/start` 返回 `thread-1`
3. 用户还没发首个 turn，或者稍后在同一个 TUI 中又 `/new`
4. 出现第二次顺序 `thread/start`

合同要求：

- 首个 `thread/start` 一旦成功返回并绑定 seed
- 这份 launch seed 就算“已经花掉”
- 后续顺序第二次 `thread/start` 不再继承这份 seed

也就是说，不允许：

- 第二个新 thread 又偷偷拿到同一份 seed

### 5.2 并发 `thread/start`

这是较少见路径，但必须 fail-close。

例子包括：

- 客户端异常重入
- 请求重试 / 重发
- 多 websocket 连接同时撞进同一个 proxy 会话

当前合同不是：

- 第一个 inflight 请求拿 seed，第二个静默创建一个不带 seed 的新 thread

而是：

- 当 launch seed 仍处于 unbound 状态、且已被一条 `thread/start` 预留时
- 后续并发 `thread/start` 直接本地拒绝

拒绝原因是：

- `feishu-codex` 不接受“同一个 `fcodex` 会话里，用户以为自己启动的是带 seed 的 thread，但实际上系统悄悄给了一个不带 seed 的新 thread”

所以这里采用 fail-close，而不是模糊 best-effort。

## 6. reservation 合同

### 6.1 reservation 的所有权

launch seed 的 reservation 属于：

- 当前 proxy 进程级共享状态

不属于：

- 某条单独 websocket 连接

这点很重要，因为 proxy 明确存在：

- lookup 后重连
- 连接断开后的 idle 保活窗口
- 多连接进入同一个 proxy 进程

如果 reservation 只挂在 gate 上，就会出现连接切换后事实源漂移。

### 6.2 reservation 的释放

下列情况应释放 reservation：

1. 对应的 `thread/start` 返回 error
2. `thread/start` 响应没有拿到有效 `thread_id`

如果连接在 seed 绑定到 `thread_id` 之前就关闭，不能一概而论地释放 reservation。

这时要分两种情况：

1. 能明确确认这条 `thread/start` 没有成功落到 backend
   - 才允许释放
2. 结果未知
   - 则把当前 proxy 会话标记为 outcome unknown
   - 后续对这份 one-shot seed 按 fail-close 阻断

### 6.3 reservation 的消费

只有当：

- `thread/start` 成功返回
- 并拿到明确 `thread_id`

reservation 才会真正被消费，并把 seed 绑定成 pending threadwise seed。

## 7. 重连合同

### 7.1 绑定前断连

如果连接在 `thread/start` 成功返回前断开：

- launch seed 仍然是 unbound

不能直接假设：

- reservation 一定可以安全释放

因为这时可能出现：

- backend 已经接收并处理了带 seed 的 `thread/start`
- 但本地在断连前没有看到响应

因此当前合同是：

1. 如果结果可确认失败
   - 释放 reservation
   - 后续 `thread/start` 可以重新竞争 seed
2. 如果结果未知
   - 当前 proxy 会话进入 outcome unknown
   - 后续新建 thread 对这份 seed 按 fail-close 拒绝
   - 用户需要退出并重新启动 `fcodex`，而不是在同一 proxy 会话里重试复用

### 7.2 绑定后断连

如果：

- `thread/start` 已成功返回
- `thread_id` 已拿到
- seed 已绑定成 pending threadwise seed
- 但首个成功 turn 还没发生

这时连接断开或 gate 关闭：

- **不能**清掉这份 pending seed
- 它应继续留在 proxy 进程级共享状态里

这样后续重连后，对同一个 provisional thread 的 `thread/resume` 仍能读到这份 pending seed。

### 7.3 pending seed 的重连后行为

对同一个 provisional thread 重连后：

- `thread/resume` 仍应继续注入 pending 的 `profile` / `memory`
- 直到该 thread 首次成功 materialize 并 promote

也就是说，pending seed 在合同上属于：

- 当前 proxy 会话里的 logical continuity

而不是：

- 某条短暂 websocket 连接的私有内存

## 8. 清理与终止合同

### 8.1 promote 后清理

当 pending seed 成功 promote 为正式 thread-wise persist state 后：

- 清掉 pending seed

### 8.2 `thread/closed`

如果 thread 被明确关闭：

- 清掉对应 pending seed
- 释放相关 runtime / interaction lease

### 8.3 没有 materialize 就退出

如果用户开了 `fcodex`，拿到 provisional shell，但一句话没发就退出：

- 不写正式 thread-wise store

这仍然是本合同的核心判断之一。

## 9. 当前已落地的实现约束

截至 2026-05-12，本地 `fcodex` proxy 已按本文合同收口到以下行为：

1. launch seed / reservation / pending threadwise seed 已提升为 proxy 进程级共享状态
2. 顺序第二次 `thread/start` 不会再次继承首个 thread 的 launch seed
3. 并发 `thread/start` 在 seed 尚未绑定时会 fail-close，本地返回错误
4. `thread/start` 报错会释放 reservation
5. 如果连接在 `thread/start` 结果未知时关闭，当前 proxy 会话会进入 outcome unknown，并阻断后续 seed 复用
6. 绑定成 pending seed 后，即使 websocket 断开，重连后 `thread/resume` 仍可继续使用该 pending seed
7. 只有首个成功 `turn/completed` 才会把 seed promote 到正式 stores

## 10. 仍未被本文一并解决的更大系统问题

本文这次落地的是：

- 本地 `fcodex` proxy 会话级合同

不是：

- 整个 `feishu-codex` 所有入口都已经完全统一

因此下列问题仍需单独讨论和收口：

1. 飞书侧 binding continuity 与 provisional replacement 的全链路合同
2. `feishu-codexctl` 对 explicit provisional `thread_id` 的 fail-close 语义
3. 飞书侧、本地控制面、本地 `fcodex` 三者之间的统一文案与用户提示

## 11. 一句话版本

> `feishu-codex` 的 `profile` / `memory` 是 thread-owned next-load state；
> 但只有 materialized logical thread 才拥有正式的 thread-wise persist state。
> `fcodex` 在 provisional 阶段只允许持有 proxy 会话级 pending seed；
> 并发新建 thread 时按 fail-close 处理；
> 如果连接在 `thread/start` 结果未知时关闭，也按 fail-close 阻断当前 proxy 会话继续复用这份 one-shot seed。
