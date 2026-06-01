# 运行时控制面合同

英文原文：`docs/contracts/runtime-control-surface.md`

本文定义飞书侧控制面的正式语义。

## 1. 当前只有两类设置入口

### 1.1 实例 startup baseline

入口：

- `/profile`
- `/profile-clear`

语义：

- 管理当前实例 managed backend 的启动基线
- 不直接改当前 thread
- 只在 backend 启动或 reset 后重启时真正生效

### 1.2 binding-wise next-turn settings

入口：

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

语义：

- 管理当前飞书会话后续 turn 的 override
- 主路径在 `turn/start` 被消费
- 不写入项目自管的 thread 级持久化状态

## 2. 已移除的设置面

以下入口已不再属于正式合同：

- `/memory`
- 任何 thread-wise memory 控制面

如果用户希望切换 memory/provider 之类上游进程级能力，应通过：

- 实例 startup profile
- 上游 `~/.codex/config.toml`
- profile-v2

而不是通过本项目维护 thread 级设置。

## 3. 其他核心状态轴

除了设置之外，控制面还长期区分三条状态轴：

1. `binding`
   - 当前会话逻辑上指向哪个 thread
2. `attach / detach`
   - 当前会话是否接收该 thread 的飞书推送
3. `backend / live runtime`
   - 该 thread 是否在 backend 中 loaded，以及当前由谁持有 live runtime

这些状态轴与设置是平行概念，不能混读、混写、混解释。

## 4. `/profile` 的正式语义

`/profile` 虽然仍放在“线程设置”工作区里，但真实作用范围是：

- 当前实例

因此：

- `/profile <name>`：改实例 startup profile
- `/profile-clear`：清空实例 startup profile override
- 如果希望当前实例立刻切过去，应继续执行 reset backend

## 5. turn-time 设置的正式语义

`/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode`：

- 都属于当前 binding 的 next-turn 设置
- 默认读回当前 binding 的持久化 intent
- 不是实例级 baseline
- 也不是 thread 级 persisted truth

其中：

- `auto` 表示“不显式覆盖”
- 它不再对应任何项目自管的 thread 级 fallback 状态

## 6. reset backend 的副作用边界

实例 reset backend 时：

- backend 进程会重启
- binding bookmark 保留
- 当前实例的相关飞书推送会先 detach
- startup profile 保留
- binding-wise next-turn 设置保留

reset backend 不会做的事：

- 不会重写 thread 历史
- 不会自动重新 attach 所有会话
- 不会把 binding 设置升级成 thread 级设置

## 7. `/status` 应展示什么

`/status` 与相关诊断页应分别展示：

- 实例 startup profile
- 当前 binding 的 next-turn overrides
- attach / detach 与 live runtime 状态

它们不应再展示：

- thread-wise memory setting
- “下次 resume 该 thread 时，本项目还会额外注入什么 memory 配置”
