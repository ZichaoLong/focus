# 本地命令与 Thread Profile 合同

英文原文：`docs/contracts/local-command-and-thread-profile-contract.md`

本文只澄清四件事：

- 本地三个入口 `feishu-codex`、`feishu-codexctl`、`fcodex` 的职责边界
- thread-wise profile 在本地和飞书侧分别怎么生效
- thread-wise memory mode 在本地和飞书侧分别怎么生效
- 为什么本地命令面现在统一使用 attach / detach，而不再对外暴露 release-runtime

## 1. 三个本地入口

### 1.1 `feishu-codex`

负责：

- 安装
- service 生命周期
- autostart
- 实例管理
- skill 安装等项目级辅助动作

不负责：

- 进入 Codex TUI
- 查看单个 binding / thread 的底层状态

### 1.2 `feishu-codexctl`

负责：

- 查看运行中的实例
- 查看目标实例的 service / binding / thread 状态
- 做有限的 binding / thread / image 管理动作

不负责：

- 进入 Codex TUI
- 直接改写上游线程内部历史

### 1.3 `fcodex`

负责：

- 恢复本地 live thread
- 进入 Codex TUI
- 作为本地独立 frontend 订阅 backend thread

它不是：

- 飞书命令面的镜像
- service 管理 CLI

## 2. 本地命令面的正式命名

当前对外正式命名应统一为：

- `service attach`
- `binding attach`
- `binding detach`
- `thread attach`
- `thread detach`

底层内部仍可能调用：

- `thread/unsubscribe`

但这只是服务内部协议实现，不再是用户概念。

## 3. `fcodex` 的本地路由合同

`fcodex` 现在明确拆分三类事实：

1. `thread identity`
   - 目标 thread 是谁
   - 来源可以是显式 `thread_id`，也可以先把 `thread_name` 解析成真实 `thread_id`
2. `live runtime owner`
   - 当前是谁持有 machine-global 的 live runtime claim
   - 这条 claim 的事实源是 `ThreadRuntimeLease`
3. `binding bookmark`
   - 某个会话 / 实例“记得自己上次指向过哪个 thread”
   - 只用于诊断与展示，不参与 `fcodex resume` 自动路由

`fcodex` 只保留两类路由语义：

1. 带明确 thread 目标的恢复：
   - `fcodex resume <thread_id|thread_name>`
2. 不带明确 thread 目标的启动：
   - `fcodex`
   - `fcodex <prompt>`
   - 以及其他非 `resume` 的 TUI 进入路径

正式合同是：

- 带 thread 目标的恢复，必须 fail-close；不得使用 binding bookmark 推断实例，也不得依赖 `default-running` 兜底
- 不带 thread 目标的启动，仍可保留便捷兜底：
  - 显式 `--instance` 优先
  - 否则唯一运行中的实例优先
  - 否则运行中的 `default` 可作为兜底
  - 再否则必须要求显式 `--instance`

对于带 thread 目标的恢复：

- `resume <thread_name>` 只先做名字解析，得到真实 `thread_id` 后，后续路由规则与 `resume <thread_id>` 完全一致
- 若存在 `live runtime owner`，只能路由到该实例
- 若不存在 `live runtime owner`，且当前恰好只有一个运行中的实例，则可路由到该实例
- 若不存在 `live runtime owner`，且运行中的实例不是唯一，就必须拒绝并要求显式 `--instance`
- 若显式传了 `--instance`，且它与 `live runtime owner` 冲突，也必须拒绝
- 路由到目标实例后，还必须继续检查其他运行中实例是否仍把该 thread 保持为 `loaded`
- 只要其他实例仍报告 `loaded`，就必须拒绝；不支持跨实例 hot takeover
- 如果无法验证其他实例的 thread status，也必须拒绝
- 只有 loaded gate 通过后，才允许继续争抢 `ThreadRuntimeLease`

## 4. profile / memory 都属于 thread-wise next-load 设置

这条规则在本地与飞书侧完全一致：

- 对受支持的恢复路径，同一个 thread 从 unloaded 恢复为 loaded 时，应使用同一份已持久化的 thread-wise 设置
- binding 只决定“当前会话记住哪个 thread”
- attach / detach 只决定“当前飞书会话收不收推送”

共享 next-load 生效与 direct-write / reset-backend 规则，以
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准。

## 5. 本地如何改 profile

### 5.1 新线程

新线程可以通过：

- `fcodex -p <profile> new`
- 或飞书 `/new` 后再 `/profile <name>`

### 5.2 已有线程

已有线程的直接改写条件，以
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准。

因此：

- `fcodex resume <thread> -p <profile>` 遇到 loaded thread 必须拒绝
- 不应要求用户先去理解 release-runtime / unsubscribe
- 推荐路径应是飞书 `/profile <name>`，必要时走 reset-backend

### 5.3 thread-wise memory mode

正式合同是：

- 飞书 `/memory [off|read|read_write]` 负责改写 thread-wise memory mode
- 本地 `feishu-codexctl thread memory --thread-id <id>` 是正式的独立查看入口
- 本地 `feishu-codexctl thread memory --thread-id <id> --mode <off|read|read_write>` 是正式的独立改写入口
- 对受支持的恢复路径，`fcodex resume <thread>` 恢复该 thread 时，会自动沿用已持久化的 memory mode
- `codex.yaml` 里的 `default_thread_memory_mode` 只是项目支持的新线程创建路径上的 seed
- 若要理解共享的 direct-write / reset-backend 条件，以 `docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准
- memory mode 自身的业务语义，以 `docs/contracts/thread-memory-semantics.zh-CN.md` 为准

## 6. reset-backend 在本地与飞书侧的关系

无论从飞书还是本地 `feishu-codexctl service reset-backend` 触发：

- backend 会被重置
- binding bookmark 保留
- 相关 Feishu binding 变成 `detached`
- thread-wise profile/provider 保留

之后若想继续收到飞书推送，应显式选择：

- 当前线程 attach
- 当前实例 attach
- 保持 detached

## 7. 为什么不用 release-runtime 作为主文案

因为它把三层概念混在了一起：

- binding 是否还记得 thread
- 飞书是否还接收推送
- backend 是否还 loaded

当前更清晰的合同是：

- `binding`
- `attach / detach`
- `backend / live runtime`

这样本地与飞书侧可以共享同一套心智模型，而不必再让用户猜 “release 到底 release 了哪一层”。
