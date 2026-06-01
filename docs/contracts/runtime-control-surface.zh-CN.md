# 运行时控制面合同

英文原文：`docs/contracts/runtime-control-surface.md`

本文是飞书侧运行时控制面的用户合同。

## 1. 控制面只区分三类设置

### 1.1 实例 startup profile

入口：

- `/profile`
- `/profile-clear`

语义：

- 管理当前实例 managed backend 的启动基线
- 不直接改当前 thread
- 改完后要等下一次 backend 启动 / reset 才真正生效

### 1.2 thread-wise next-load memory

入口：

- `/memory`

语义：

- 管理当前 thread 的 memory mode
- 写入后在下次 `thread/resume` / 对应 startup seed 路径生效
- 不是 turn-time override

### 1.3 binding-wise next-turn 设置

入口：

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

语义：

- 管理当前飞书会话后续 turn 的 runtime override
- 主路径在 `turn/start` 被消费
- 不写 thread-wise next-load state

## 2. 其他核心状态轴

除了设置之外，控制面还长期区分三条状态轴：

1. `binding`
   - 当前会话逻辑上指向哪个 thread
2. `attach / detach`
   - 当前会话是否接收该 thread 的飞书推送
3. `backend / live runtime`
   - 该 thread 是否在 backend 中 loaded，以及当前由谁持有 live runtime

这些状态轴与设置是平行概念，不能混成一件事。

## 3. `/profile` 的正式语义

`/profile` 当前虽然仍放在“线程设置”工作区里，但它的真实作用范围是：

- **当前实例**

这么放只是因为用户通常在处理当前线程时，也会顺手处理 backend 基线。

因此：

- `/profile <name>`：改实例 startup profile
- `/profile-clear`：清空实例 startup profile override
- 若需要当前实例立刻切过去，应继续执行 reset backend

## 4. `/memory` 的正式语义

`/memory` 才是当前正式保留的 thread-wise next-load 设置入口。

它有三类结果：

1. 直接写入
   - 目标 thread 已 verifiably globally unloaded
2. 提供“应用并重置 backend”
   - 当前实例可通过 reset-backend 收口
3. fail-close
   - 当前无法安全写入

## 5. turn-time 设置的正式语义

`/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode`：

- 都属于当前飞书 binding 的 next-turn 设置
- 默认读回的是当前 binding 的持久化 intent
- 不是 thread snapshot 真相
- 也不是实例级 startup baseline

其中：

- `auto` 表示“不显式覆盖”
- 它不表示“把某个 thread-wise 状态清空为默认”

## 6. reset backend 的副作用边界

实例 reset backend 时：

- backend 进程会重启
- binding bookmark 保留
- 当前实例的相关飞书推送会先 detach
- thread-wise memory store 保留
- startup profile 保留
- binding-wise next-turn 设置保留

reset backend 不会做的事：

- 不会重写 thread 历史
- 不会自动把所有会话重新 attach
- 不会把 binding 设置升级成 thread-wise 设置

## 7. 状态页应该读什么

`/status` 与相关诊断页应分别展示：

- 实例 startup profile
- 当前 thread 的持久化 memory mode
- 当前 binding 的 next-turn overrides

它们不应该再展示：

- “当前 thread-wise profile”
- “re-profile possible”

因为那已经不是当前正式合同的一部分。
