# `bind/rebind` 事务性缺口记录

日期：2026-05-12

## 1. 结论

当前 `feishu-codex` 在 binding 切换 thread 的主链路上，存在一个明确的事务性缺口：

- 内存态 runtime state 会先被修改
- 旧 thread 的本地订阅也可能先被移除
- 持久化 `chat_bindings.json` 若在中途失败，当前流程不会回滚前面的内存态与订阅态修改

因此，失败结果不是“完全没生效”，而是可能留下一个**部分提交**状态。

这不是 provisional thread 的 memory seed 清理问题；那只是另一条独立链路。本问题发生在更核心的 `bind/rebind` 本身。

## 2. 相关位置

- `bot/binding_runtime_manager.py`
  - `apply_persisted_runtime_state_message_locked(...)`
  - `bind_thread_locked(...)`
  - `clear_thread_binding_locked(...)`
- `bot/codex_handler.py`
  - `_bind_thread(...)`

当前关键事实：

1. `apply_persisted_runtime_state_message_locked(...)` 先改 `state`，再调用 `sync_stored_binding_locked(...)` 落盘。
2. `bind_thread_locked(...)` 在改到新 thread 之前，可能已经：
   - 释放旧 thread 的 interaction lease
   - 取消旧 thread 的本地订阅
   - 执行 `on_thread_replaced(...)` 清掉当前执行卡 / turn 状态
3. 如果后续落盘抛错，函数会异常退出，但前面这些状态改动不会自动恢复。

## 3. 失败窗口

以 `rebind old -> new` 为例，当前顺序大致是：

1. 读取当前 binding 的 runtime state
2. 如果旧 thread 不同于新 thread：
   - 释放旧 thread interaction lease
   - 从本实例 thread subscriber 集合里移除旧 thread
   - 清理绑定上的执行态
3. 把 `current_thread_id/current_thread_title/feishu_runtime_state/working_dir` 写入内存态
4. 同步写入 `chat_bindings.json`
5. 把该 binding 订阅到新 thread

真正的缺口在第 3-4 步之间：

- 第 3 步已经把内存态切到了新 thread
- 第 2 步已经把旧 thread 的本地订阅撤掉了
- 但第 4 步如果失败，当前 binding 既没有可靠落盘，也还没完成新 thread 订阅

## 4. 用户可感知的坏结果

如果 `chat_bindings.json` 保存失败，用户看到的可能是：

1. 飞书侧操作返回“失败”。
2. 旧 thread 的本地订阅已经被撤掉。
3. 当前进程内存里，这个 binding 又像是已经切到了新 thread。
4. 但新 thread 的订阅未必真正建立完成。
5. 服务重启后，因为落盘没成功，又可能回到旧 binding 事实。

这会形成典型的单一事实源破裂：

- 内存态是一套
- 订阅态是一套
- 落盘态又是一套

## 5. 为什么这是架构问题

这不是“异常文案不够清楚”。

问题本质是：当前实现把一个需要原子收口的状态迁移，拆成了若干个会对外可见的副作用步骤，但没有事务边界，也没有补偿逻辑。

对这个仓库的设计偏好而言，这类行为有三个明显问题：

1. 单一事实源被打穿。
2. 失败后状态不可直观推断。
3. 后续修 bug 时很容易继续叠加“遇错再补一刀”的分支。

## 6. 最小复现思路

可以直接在单元测试里构造：

1. 先让一个 binding 绑定在 `thread-old`
2. 调用 `bind_thread_locked(...)`，目标切到 `thread-new`
3. 在 `ChatBindingStore.save(...)` 上打桩，让它抛异常
4. 观察失败后的三个面：
   - 内存态 `state`
   - thread subscriber 集合
   - 落盘文件

预期会看到：

- `state["current_thread_id"]` 已经不是旧值
- `thread-old` 的 subscriber 可能已经消失
- 持久化并没有成功写入新值

当前仓库里没有覆盖这条失败路径的回归测试。

## 7. 建议合同

建议把 `bind/rebind` 明确成下面这条合同：

- 若返回成功：
  - 内存态、订阅态、落盘态三者一致切到新 thread
- 若返回失败：
  - 至少对外保持旧绑定事实不变
  - 不允许留下“旧订阅已撤，新绑定未完成，内存态已半切换”的中间态

也就是说，失败路径必须 fail-close 到**旧事实仍成立**，而不是停在半路。

## 8. 建议修法

优先建议是把 `bind_thread_locked(...)` 改成显式两阶段：

1. 先计算目标持久化状态，但不要立刻改 live state
2. 先尝试完成可保证安全的持久化准备
3. 只有在持久化成功后，再提交内存态与订阅态切换

如果现有结构不方便直接做到严格两阶段，则至少要补偿：

1. 进入 `old -> new` 切换前记录旧快照
2. 任一步失败时：
   - 恢复旧 runtime state
   - 恢复旧 thread subscriber
   - 恢复旧 interaction lease 归属
3. 确保异常返回后，调用方看到的还是旧 binding 事实

## 9. 后续测试建议

至少补三类回归：

1. `bind_thread_locked(...)` 在 `ChatBindingStore.save(...)` 抛错时，旧绑定事实保持不变。
2. `clear_thread_binding_locked(...)` 在落盘失败时，不会把 binding 留成“内存已清空但落盘仍绑定”的半状态。
3. `CodexHandler._bind_thread(...)` 失败后：
   - 不会错误释放新 thread lease
   - 不会把旧 thread 留成无订阅但仍被认为绑定中的状态

## 10. 当前处理建议

这条问题值得保留为单独执行项，但不建议和本轮 `/new` 的控制面误判修复混在一起提交。

原因：

- `/new` 问题是“把 `notLoaded` 误判成不明 loaded”
- 本问题是“状态迁移缺少事务边界”

两者层次不同，混修会让回归面和审视都变差。
