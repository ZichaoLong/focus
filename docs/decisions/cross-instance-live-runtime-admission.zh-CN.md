# 跨实例 Live Runtime 准入决策

英文原文：`docs/decisions/cross-instance-live-runtime-admission.md`

另见：

- `docs/decisions/shared-backend-resume-safety.zh-CN.md`
- `docs/contracts/runtime-control-surface.zh-CN.md`
- `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`
- `docs/architecture/fcodex-shared-backend-runtime.zh-CN.md`

## 1. 状态

本文记录下一轮改造已经对齐的目标合同。

在实现真正落地之前，当前正式行为仍以现有 contracts 与代码为准。
本文的作用，是把下一轮实现要收敛到的设计决策先固定下来。

## 2. 问题

当前机器级 `ThreadRuntimeLease` 不足以单独承担跨实例安全准入。

原因是：

- 上游 app-server 在最后一个 subscriber `unsubscribe` 后，仍会把 thread 保持
  `loaded` 约 30 分钟
- 后续的 `thread/resume` 可能直接复用这份已经加载的内存态 thread
- 因此 `lease == none` 并不推出 `backend == notLoaded`

这会带来真实的跨实例 stale-loaded 风险：实例 A 可能还留着旧的内存态
thread，而实例 B 已经基于持久化历史继续推进了对话。

## 3. 决策

### 3.1 产品合同

- thread visibility 继续全局共享
- live continuation 必须实例独占
- 跨实例迁移只支持 `cold migration only`
- 不支持跨实例 live takeover / 自动转移

### 3.2 准入模型

所有跨实例敏感路径，都必须分成两层：

1. `global loaded gate`
   - 跨实例 `attach / resume` 之前，必须先验证是否仍有其他运行中的实例报告该
     thread 为 `loaded`
   - 只要别的运行中实例仍报告它 `loaded`，就拒绝
   - 如果系统无法验证这个事实，也拒绝
2. 原子 `ThreadRuntimeLease` claim
   - 只有 loaded gate 通过后，当前实例才允许继续争抢机器级 runtime lease
   - 这层仍然保留，用来防止两个实例几乎同时观察到全局 `notLoaded` 后并发
     `resume` 的竞态

### 3.3 `ThreadRuntimeLease` 的含义

`ThreadRuntimeLease` 继续保留，但角色收窄为内部协调原语：

- 它不再是跨实例安全准入的唯一事实源
- 它是机器级原子 claim，用来阻止并发写入竞态
- 它承载 holder 元数据，例如 `service` / `fcodex`

用户侧心智模型应优先理解成：

- “另一个运行中的实例仍把这个 thread 保持在 loaded”
- 而不是“另一个实例持有了 lease”

## 4. Attach 合同

### 4.1 binding / thread / service attach

所有 attach 入口都必须服从同一套 loaded gate。

- `binding attach`：只有目标 thread 通过 gate 才允许
- `thread attach`：只有目标 thread 通过 gate 才允许
- `service attach`：是实例级批量恢复，但失败判断粒度必须是 thread

### 4.2 service attach 结果形状

`service attach` 应满足：

- 批量恢复当前实例内所有 detached bindings
- 实际处理时按 thread 分组
- 每个 thread 要么为本实例完整恢复，要么整条阻塞
- 不同 thread 之间允许部分成功
- 被阻塞的 thread 必须明确列出原因

也就是：

- 实例级批量恢复
- thread 级 fail-close
- 结果层允许部分成功

## 5. 操作面含义

- 只要另一个运行中实例还有可能保留这个 thread 的 loaded 内存态，就不做自动跨实例继续
- 源实例 reset、等待 idle unload、或显式 cold migration 都是可以接受的用户路径
- 只要 loaded 状态无法被证明安全，就必须让位于 fail-close，而不是让位于便利性

## 6. 下一轮实现范围

下一轮改造应把这个决策落到：

- Feishu attach 相关路径
- detached binding 的自动 attach / re-attach 路径
- 本地 `fcodex resume` 中与跨实例 loaded 冲突有关的准入逻辑
- 状态展示与拒绝文案，让用户看到的是“loaded elsewhere”，而不是只看到
  lease 术语
