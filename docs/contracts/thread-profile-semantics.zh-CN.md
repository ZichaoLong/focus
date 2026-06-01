# Startup Profile 语义

英文原文：`docs/contracts/thread-profile-semantics.md`

说明：本文件沿用历史文件名，但当前定义的已经不是“thread-wise profile”，而是
**managed backend 的实例级 startup profile**。

## 1. 定义

- startup profile 是 **实例级** 设置，不是 thread-wise 状态。
- 它只适用于 `app_server_mode=managed` 的实例。
- 它的事实源是实例配置里的 `managed_startup_profile`。
- 它的取值空间来自共享 `CODEX_HOME` 下可用的 profile-v2 名称。
- 它的作用是：为下一次启动的 managed backend 提供一层启动基线。

它不表示：

- 当前 thread 的 next-load profile
- 当前 Feishu 会话的 turn-time override
- 当前已加载 backend 的即时 live truth

## 2. `/profile` 与 `/profile-clear`

飞书侧：

- `/profile`
  - 无参数：查看当前实例的 startup profile 与可选 profile 列表
  - 带参数：把当前实例的 startup profile override 改为目标 profile
- `/profile-clear`
  - 清空当前实例的 startup profile override
  - 回落到共享 `CODEX_HOME/config.toml` 顶层默认配置

这些命令：

- 不直接改写当前 thread
- 不写 thread-wise 持久化状态
- 不保证当前已加载 backend 立即变更

## 3. 何时生效

startup profile 会在以下边界被消费：

- managed backend 启动
- managed backend reset 后重启

因此：

- 改完 `/profile` 后，下一次 managed backend 启动才会真正吃到它
- 若希望当前实例立刻切过去，应再执行 reset backend

## 4. reset backend 后的可观察结果

当用户通过 `/profile` 或 `/profile-clear` 选择“应用并重置 backend”时：

- 新 backend 会按新的 startup profile 启动
- 若当前 bookmark 指向正常 thread，binding bookmark 保留
- 若当前 bookmark 仍是 provisional shell，或该 thread 已不存在，实现可在 reset 恢复时清空当前会话 bookmark
- 当前实例的相关飞书推送会先变成 `detached`
- 结果卡会继续提供 `附着当前线程` / `附着当前实例` / `保持 detached`

这一步改变的是：

- backend 进程启动基线

不是：

- 某个 thread 的逻辑身份
- 某个会话的绑定关系

## 5. 与其他设置的边界

当前项目当前只保留两类可写设置：

1. 实例 startup baseline
   - 本文件定义的 startup profile
2. binding-wise next-turn 设置
   - `docs/contracts/runtime-control-surface.zh-CN.md`

`/profile` 只属于第 1 类。

## 6. 非目标

当前合同明确不再承诺：

- “profile 是 thread-wise next-load truth”
- “同一个 thread resume 时应自动沿用持久化 profile slice”
- “飞书侧 `/profile` 与本地 `fcodex -p` 在语义上等价”
- “只要 thread unloaded，就能在本项目里把 profile 当 thread 设置来写”

本项目现在把这些旧心智收缩为：

- startup profile 只管理 managed backend 的启动基线
- 不再保留项目自管的 thread-wise next-load 设置层
