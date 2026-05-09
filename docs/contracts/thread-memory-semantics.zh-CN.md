# Thread Memory Mode 语义

英文原文：`docs/contracts/thread-memory-semantics.md`

本文只定义 thread-wise memory mode 自身的业务语义与入口合同。
共享的 next-load 生效与 direct-write / reset-backend 规则，以
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准。

## 1. 基本事实

- memory mode 是 **thread-wise** 状态，不是 binding-wise 状态。
- 对受支持的恢复路径，同一个 thread 从 unloaded 恢复为 loaded 时，应使用同一份已持久化的 thread-wise memory mode。
- 本项目对外只暴露一个统一概念：`memory mode`，不直接把上游的两个布尔旋钮暴露给飞书用户。

当前正式支持三个取值：

- `off`
- `read`
- `read_write`

它们与上游 resume 配置的映射固定为：

- `off`
  - `memories.use_memories = false`
  - `memories.generate_memories = false`
  - `thread/memoryMode/set = disabled`
- `read`
  - `memories.use_memories = true`
  - `memories.generate_memories = false`
  - `thread/memoryMode/set = disabled`
- `read_write`
  - `memories.use_memories = true`
  - `memories.generate_memories = true`
  - `thread/memoryMode/set = enabled`

## 2. 它控制的是什么

thread-wise memory mode 控制的是：

- 该 thread 未来 resume 后是否读取 memory
- 该 thread 未来 resume 后是否允许生成 / 写入 memory

它**不**表示：

- 每个 thread 有独立的 memory 仓库
- binding 可以各自看到不同 memory mode

上游 memory 数据根目录仍是全局 `CODEX_HOME/memories`。
不同 thread 的差异只体现在“这个 thread 读取 / 生成 memory 的方式”，不是各自拥有隔离存储。

## 3. 飞书侧 `/memory [off|read|read_write]`

`/memory` 是当前 thread 的正式 memory mode 管理入口。

它沿用共享的 next-load 设置规则，因此有三类结果：

1. 直接写入
   - 共享 direct-write 条件已满足
2. 提供 “应用并重置 backend”
   - 共享 direct-write 条件未满足，但当前实例可通过 reset-backend 收口
3. fail-closed
   - live runtime 由别的实例持有，或当前实例无法安全重置

## 4. reset-backend 后的状态

通过 `/memory` 触发 backend reset 后：

- binding bookmark 保留
- 相关 Feishu binding 会变成 `detached`
- thread-wise memory mode 写入成功后立即持久化
- 不自动保证继续接收飞书推送

结果卡必须给用户明确选项：

- `附着当前线程`
- `附着当前实例`
- `保持 detached`

## 5. 本地行为

当前本地命令面没有单独的 thread-wise memory mode 改写命令。

正式合同是：

- 飞书 `/memory` 负责改写 thread-wise memory mode
- `fcodex resume <thread>` 在恢复该 thread 时，会自动带上已持久化的 memory mode
- 新建 thread 当前没有“实例级默认 memory mode”这一层用户概念

这意味着：

- 若某个 thread 已在飞书侧设置过 memory mode，本地 `fcodex` 下次 resume 会沿用它
- 若 thread 当前仍 loaded，要让新 memory mode 生效，仍应遵循 unload / reset-backend 路径，而不是承诺热更新
- 裸 `codex` 或其他合同外入口直接改动 runtime / config 所造成的分叉，不由本项目兜底统一

## 6. 与 `/attach`、`/detach` 的关系

- `/detach`
  - 只是暂停某个飞书会话接收推送
  - 不等于 thread 已 globally unloaded
- `/attach`
  - 只是恢复推送
  - 不修改 thread-wise memory mode

也就是说：

- memory mode 管理与 attach/detach 是两条不同状态轴

## 7. 不再支持的旧心智

以下说法当前都不准确：

- “memory 是当前飞书会话自己的开关”
- “只要 detach 就能直接改 memory”
- “memory mode 改完会立刻热更新所有已 loaded thread”

当前准确说法是：

- memory mode 是 thread-wise
- next-load 生效与 direct-write 规则，以共享合同为准
