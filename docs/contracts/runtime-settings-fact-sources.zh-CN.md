# 运行时设置的事实源与生效边界

英文原文：`docs/contracts/runtime-settings-fact-sources.md`

本文定义当前项目在“设置写入后，哪里才算事实源”这个问题上的统一口径。

## 1. 当前只保留两类可写设置

### 1.1 实例 startup baseline

当前唯一正式成员：

- managed backend startup profile

它的特点是：

- 作用对象是实例，不是 thread
- 写后持久化在实例配置里
- 真正生效点是 backend 启动或 reset 后重启

### 1.2 binding-wise next-turn settings

当前正式成员：

- model
- effort
- approval
- permissions
- collaboration mode

它们的特点是：

- 作用对象是当前飞书 binding
- 写后持久化在 binding runtime settings
- 主生效点是 `turn/start`

## 2. 当前不再保留项目自管的 thread-wise next-load 设置

以下能力已经移除，不再是本项目合同的一部分：

- `/memory`
- `feishu-codexctl thread memory`
- `new_thread_memory_mode_seed`
- `ThreadMemoryModeStore`
- 项目自管的 thread 级 memory/provider 恢复状态

因此，当前项目不会再维护一份“下次 resume 某个 thread 时，本项目额外注入什么 memory 配置”的持久化事实源。

## 3. 仍然存在的一类只读事实：live runtime / upstream snapshot

有些信息仍然会被本项目读取，但它们不是本项目持久化设置：

- 当前 loaded backend 的 live 状态
- 上游 thread snapshot
- 上游 `config/read` 读到的 runtime 视图

这些值可用于：

- `/status`
- 调试输出
- 诊断卡片

但它们不应被解释成：

- 本项目自己的可写设置层
- 飞书 `/profile` 或 `/model` 之类命令的持久化事实源

## 4. 两类可写设置对照表

| 设置类 | 写后持久源 | 正式生效边界 | 主要读侧 |
| --- | --- | --- | --- |
| 实例 startup profile | 实例配置 `managed_startup_profile` | backend 启动 / reset 后重启 | `/profile`、`/status`、本地实例诊断 |
| binding-wise next-turn | 当前 binding 的持久化 runtime settings | `turn/start` | `/status`、设置卡片、preflight |

## 5. 实例 startup baseline 的判断原则

如果问题是在问：

- “这个实例下次启动 backend 会吃什么基线”

先看：

- 实例配置里的 startup profile

不要先看：

- 当前 thread
- 当前飞书会话的 turn-time override

## 6. binding-wise next-turn 的判断原则

如果问题是在问：

- “这个飞书会话下一轮会带什么 model / effort / permissions”

先看：

- 当前 binding 的持久化 runtime settings

其中：

- `auto` 的语义仍是“不显式覆盖”
- 它不再对应任何项目自管的 thread 级持久化状态

## 7. 一条维护规则

后续若再新增设置，必须先明确它属于哪一类：

1. 实例 startup baseline
2. binding-wise next-turn settings
3. 只读诊断视图

在没有完成归类之前，不应把它做成新的命令面或持久化状态层。
