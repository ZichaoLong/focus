# Thread Profile 语义

英文原文：`docs/contracts/thread-profile-semantics.md`

本文只定义 thread-wise profile 的生效与切换合同。

## 1. 基本事实

- profile 是 **thread-wise** 状态，不是 binding-wise 状态。
- 一个 thread 在任意前端重新 resume 时，都应看到同一个 thread-wise profile。
- 当前项目不再保留“实例级默认 profile”这一层用户概念。

## 2. 何时能直接改

thread-wise profile 只有在 thread **verifiably globally unloaded** 时，才允许直接写入。

这要求至少同时满足：

- 当前 thread 没有 attached 的 Feishu binding
- 当前 thread 没有 live runtime lease
- backend 侧已确认该 thread 不在内存

所以：

- 单纯 `detached` 不够
- 只关掉一个飞书会话不够
- 本地 `fcodex` 仍开着时通常也不够

## 3. 飞书侧 `/profile [name]`

`/profile` 是当前 thread 的正式 profile 管理入口。

它有三类结果：

1. 直接写入
   - 当前 thread 已 verifiably globally unloaded
2. 提供 “应用并重置 backend”
   - 当前 thread 还没满足直接写入条件，但当前实例可通过 reset-backend 收口
3. fail-closed
   - live runtime 由别的实例持有，或当前实例无法安全重置

## 4. reset-backend 后的状态

通过 `/profile` 触发 backend reset 后：

- binding bookmark 保留
- 相关 Feishu binding 会变成 `detached`
- thread-wise profile/provider 写入成功后立即持久化
- 不自动保证继续接收飞书推送

结果卡必须给用户明确选项：

- `附着当前线程`
- `附着当前实例`
- `保持 detached`

## 5. `/attach` 与 `/detach` 的关系

- `/detach`
  - 只是暂停某个飞书会话接收推送
  - 不等于 thread 已 globally unloaded
- `/attach`
  - 只是恢复推送
  - 不修改 thread-wise profile

也就是说：

- profile 管理与 attach/detach 是两条不同状态轴

## 6. 本地 `fcodex -p`

`fcodex resume <thread> -p <profile>` 只有在 thread 当前未 loaded 时才允许改写 profile。

如果 thread 仍 loaded，应明确拒绝，并告诉用户：

- 去掉 `-p/--profile` 可直接进入当前会话
- 如果真要改 profile，应等待 thread verifiably globally unloaded
- 常见替代路径是飞书 `/profile <name>` + reset-backend

## 7. 不再支持的旧心智

以下说法当前都不准确：

- “先 release-runtime，再改 profile”
- “只要 unsubscribe，profile 就一定可写”
- “实例有自己的默认 profile，会影响现有 thread”

当前准确说法是：

- profile 是 thread-wise
- 是否可写取决于 thread 是否 verifiably globally unloaded
- 不满足时，应通过 reset-backend 路径收口，而不是要求用户手工理解更多低层动作
