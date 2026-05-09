# 运行时控制面合同

英文原文：`docs/contracts/runtime-control-surface.md`

本文是当前运行时词汇与控制动作的权威合同。

## 1. 三层心智模型

当前系统对外只保留三层心智模型：

1. `binding`
   - 某个飞书会话当前记住哪个 thread
2. `attach / detach`
   - 某个飞书会话当前是否接收这个 thread 的飞书推送
3. `backend / live runtime`
   - 这个 thread 当前是否在 backend 中 loaded，以及 live runtime 归哪个实例 / 本地前端持有

上游 `thread/unsubscribe` 仍然存在，但它只是内部协议动作，不再作为用户概念。

## 2. 核心词汇

### 2.1 `binding`

表示一个飞书会话逻辑上当前指向哪个 thread。

- `unbound`
- `bound`

它回答的是：

- “这个会话下一条默认接着哪个 thread 说话？”

它不回答：

- 是否正在接收推送
- backend 是否 loaded

### 2.2 `feishu push`

表示当前飞书会话是否接收该 thread 的推送。

- `attached`
- `detached`
- `not-applicable`

它回答的是：

- “这个飞书会话现在会不会收到该 thread 的飞书推送？”

### 2.3 `backend thread status`

表示该 thread 在当前实例 backend 里的状态。

典型值：

- `notLoaded`
- `idle`
- `active`
- `systemError`

这和飞书会话是否 attached 是两条不同状态轴。

### 2.4 `live runtime owner`

表示 machine-global 的 live thread 运行时归谁持有。

它可能是：

- 某个 `feishu-codex` service 实例
- 某个本地 `fcodex` / proxy holder
- 无

它回答的是：

- “当前哪个实例 / 本地前端真正占着这条 live thread？”

它不是跨实例 attach / resume 的唯一安全事实源。

- 跨实例继续前，必须先确认其他运行中实例没有仍把该 thread 保持为 `loaded`
- 只有这层 loaded gate 通过后，当前实例才可以继续争抢 `ThreadRuntimeLease`

### 2.5 `interaction owner`

表示当前谁可以对这条 thread 发起下一轮写入、处理中断、审批、补充输入。

它和 `live runtime owner` 不完全相同：

- `live runtime owner` 关注谁持有 live runtime
- `interaction owner` 关注谁拥有当前这轮交互控制权

## 3. 强约束

### 3.1 首次 attach / 最后一次 detach

对 Feishu 服务自身而言：

- 第一个 binding 从 detached 变 attached 时，服务必须确保自己已对该 thread 建立订阅
- 某个 thread 的最后一个 attached Feishu binding 变 detached 时，服务必须自动停止自己对该 thread 的 Feishu-side 订阅
- 仅有本地 `attached` 标记还不够；只有服务自己的 backend 连接重新建立了真实 thread 订阅事实，才允许把状态记为 `attached`

这条约束只约束 Feishu 服务自己。

它不约束本地 `fcodex`：

- 本地 `fcodex` 仍可独立订阅同一个 thread
- 所以最后一个 Feishu detach 后，backend 仍可能保持 loaded

### 3.2 重启恢复

持久化文件里的 `attached` 不能跨进程直接恢复成真 attached 事实。

因此重启或重新创建服务连接时：

- 旧的 persisted `attached` 必须降级为 `detached`
- binding bookmark 保留
- 后续 `/attach`、`/resume`、或下一条普通消息才会重新附着

### 3.3 detached prompt 的 pure reject

如果当前 binding 是 `bound + detached`，而下一条普通消息因为 live runtime / interaction / sharing 规则被拒绝：

- 必须 pure reject
- 不得偷偷 resume
- 不得偷偷新增 Feishu subscriber
- 不得把 `detached` 改回 `attached`

## 4. 关键状态组合

### 4.1 `bound + attached + idle`

合法稳态。

表示：

- 当前 chat 记住该 thread
- 当前 chat 正在接收推送
- backend 当前没有运行中的 turn

### 4.2 `bound + detached + notLoaded`

最典型的“可直接改 thread-wise profile”状态。

表示：

- binding bookmark 仍在
- 飞书当前不接收推送
- 当前实例 backend 已确认该 thread 不在内存

### 4.3 `bound + detached + idle/active`

同样合法。

表示：

- 飞书已经 detach
- 但别的订阅者仍让 backend 保持 loaded
- 最常见的是本地 `fcodex`

所以：

- `detached` 不等于 `notLoaded`

## 5. 命令合同

### 5.1 `/status`

`/status` 是 chat-scoped 摘要命令。

它只负责显示：

- 当前目录
- 当前线程
- 当前 thread 的 thread-wise profile
- 当前飞书会话后续 turn 的权限 / 审批 / 沙箱 / 协作模式

它不再承担完整调试面。

### 5.2 `/preflight`

`/preflight` 是 chat-scoped dry-run。

它可以回答：

- 下一条普通消息会 accepted 还是 blocked
- 当前 chat 的 `/detach` 是否可执行

它不能：

- 启动 turn
- 调用 resume
- 改变 binding / attached / detached / owner

### 5.3 `/detach`

`/detach` 只作用于**当前 chat binding**。

它会：

- 保留当前 binding bookmark
- 把当前 chat 从 `attached` 改成 `detached`
- 如果它是该 thread 的最后一个 attached Feishu binding，则自动让 Feishu 服务停止自己对该 thread 的订阅

它不会：

- 删除 thread
- 清空 binding
- 强制让 backend unload

### 5.4 `/attach [binding|thread|service]`

这是恢复动作。

作用域：

- `binding`
  - 只恢复当前 chat binding
- `thread`
  - 恢复当前 chat 所在 thread 上的所有 detached bindings
- `service`
  - 恢复当前实例内所有可恢复的 detached bindings

所有 attach 动作都必须 fail-closed：

- 如果其他运行中实例仍报告该 thread 为 `loaded`
- 如果无法验证其他运行中实例是否已完全 `unloaded`
- 如果 loaded gate 通过后，live runtime lease claim 仍不允许
- 如果目标 thread 已不再可恢复
- 如果当前实例无法安全取得所需运行时

`service attach` 还必须满足：

- 实例级批量恢复
- thread 级 fail-close
- 不同 thread 间允许部分成功

attach 不是只读查看动作。

- 即使 thread 当前已经 loaded，attach 也必须重新建立服务连接在 backend 侧的 thread 订阅
- 不能因为 `thread/read` 成功，就只改本地状态为 `attached`

### 5.5 `/reset-backend`

`/reset-backend` 是实例级动作。

它会：

- 重置当前实例 backend
- 保留 binding bookmark
- 保留 thread-wise profile/provider
- 保留用户配置与数据
- 让相关 Feishu binding 进入 `detached`

它不会：

- 自动删除 binding
- 自动清空 thread-wise profile
- 自动保证重新 attached

因此 reset 完成后，结果卡应直接给出：

- `附着当前线程`
- `附着当前实例`
- `保持 detached`

## 6. 本地管理面

本地 `feishu-codexctl` 的正式命令矩阵以
`docs/contracts/feishu-codexctl-command-matrix.zh-CN.md` 为准。

这里不再维护第二份命令清单；本文只定义运行时状态与控制语义。

## 7. reset-backend 与 re-profile

thread-wise next-load 设置（当前包括 profile / memory mode）的直接写入前提与 reset 路径，以
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准。

这里仅保留本运行时控制面的结果要求：

- 飞书侧 `/profile <name>` / `/memory <...>` 应优先给用户走“直接写入”或“应用并重置 backend”
- 不应要求用户先理解复杂的 detach / attach / unsubscribe 关系

## 8. 结论

当前产品对外合同必须坚持：

- `binding` 回答“记住哪个 thread”
- `attach / detach` 回答“收不收推送”
- `backend / live runtime` 回答“thread 现在在哪、归谁持有”

任何代码、CLI 文案、帮助卡、结果卡、README、合同文档，如果继续把这些层混成 “release runtime residency” 这类单一概念，都应视为合同缺口并继续收紧。
