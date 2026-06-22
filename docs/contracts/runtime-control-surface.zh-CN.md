# Runtime 控制面合同

英文原文：`docs/contracts/runtime-control-surface.md`

本文定义飞书侧控制面的正式语义。

## 1. 只剩一个可写设置族

### 1.1 binding-wise next-turn settings

入口：

- `/model`
- `/effort`
- `/approval`
- `/permissions`

语义：

- 管理当前 Feishu binding 后续 turn 的 override
- 主要在 `turn/start` 被消费
- 在恢复未 loaded thread 时，cold `thread/resume` 也可能为恢复后的第一轮
  autonomous turn 携带其中一小段 one-shot override
- 不写任何项目自管的 thread-level persisted state

## 2. 已移除的设置面

下列入口已不再属于本项目的正式合同：

- 历史上的项目自管 profile 命令
- `/memory`
- 任何 thread-wise memory 控制面

如果操作者想修改 process-level 的上游能力，例如 profile/provider 或
memory 行为，应直接通过上游 Codex 处理，而不是走项目自管的飞书设置面。

## 3. 其他核心状态轴

独立于 settings 之外，控制面仍严格区分三条状态轴：

1. `binding`
   - 当前 chat 逻辑上指向哪个 thread
2. `attach / detach`
   - 当前 chat 是否接收该 thread 的飞书推送
3. `backend / live runtime`
   - 该 thread 当前是否 loaded，以及谁拥有 live runtime

这些轴与 settings 正交，不得混淆。

## 4. turn-time settings 的正式语义

`/model`、`/effort`、`/approval`、`/permissions`：

- 都属于当前 binding 的 next-turn settings
- 默认回读 persisted binding intent
- 不是 instance baseline
- 不是 thread-level persisted truth

在这个设置族内：

- `auto` 表示“不显式 override”
- 它不再映射到任何项目自管 thread-level fallback state

## 5. reset-backend 的副作用边界

`reset-backend` 是恢复/管理工具，不是常规的 settings apply 路径。
典型用途是：

- 在跨实例 cold continue 之前，主动丢弃当前实例里陈旧的 loaded runtime
- 当同一 persisted thread 在项目外被修改后，例如用户用裸上游 `codex`
  改写了线程，再重建本实例 backend 对它的内存态视图

当实例执行 backend reset 时：

- backend 进程会重启
- binding bookmark 保留
- 相关 Feishu push 路径会先 detach
- binding-wise next-turn settings 保留

reset-backend 不会：

- 重写 thread history
- 自动把所有 chat 重新 attach
- 把 binding settings 升格成 thread-level settings
- 充当 profile 切换入口

## 6. `/status` 应展示什么

`/status` 与相关诊断应分别展示：

- 当前 binding 的 next-turn overrides
- attach/detach 状态
- live-runtime / loaded 状态

它们不应再展示：

- 项目自管 profile 设置
- thread-wise memory 设置
- “本项目会在下次 resume 时再注入的额外配置”
