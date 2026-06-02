# Runtime 设置事实源与生效边界

英文原文：`docs/contracts/runtime-settings-fact-sources.md`

本文定义统一规则：一个设置写入之后，哪一层才是它的权威事实源？

## 1. 只剩一个可写设置族

### 1.1 binding-wise next-turn settings

当前正式成员：

- model
- effort
- approval
- permissions
- collaboration mode

它们的属性：

- 作用域是当前 Feishu binding
- 持久化在 binding runtime settings 中
- 主要在 `turn/start` 被消费

## 2. 本项目不再拥有任何 thread-wise next-load setting

下列表面已被移出本项目合同：

- 历史上的项目自管 profile 命令
- `/memory`
- `feishu-codexctl thread memory`
- `new_thread_memory_mode_seed`
- 任何项目自管的 thread-level memory/provider/profile restore state

因此，本项目不再维护“某个 thread 下次 resume 时还会额外注入什么配置”这类
持久化事实源。

## 3. 只读事实族：live runtime / upstream snapshot

有些值仍会被读取，但它们不是项目自管的持久化设置：

- live loaded-backend state
- 上游 thread snapshot
- 上游 `config/read` 返回的 runtime view

这些值可以展示在：

- `/status`
- diagnostics
- admin cards

但不得把它们当成：

- 一个可写的项目设置层
- 某个已移除 legacy profile 命令背后的持久化事实源

## 4. 可写设置表

| 设置族 | 持久化源 | 正式生效边界 | 主要读侧 |
| --- | --- | --- | --- |
| binding-wise next-turn | 当前 binding 的 persisted runtime settings | `turn/start` | `/status`、setting cards、preflight |

## 5. binding-wise next-turn 的判定规则

如果问题是：

- “这个 Feishu chat 的下一轮 turn 会使用什么 model / effort / permissions？”

首先看：

- 当前 binding 的 persisted runtime settings

在这个设置族里：

- `auto` 仍表示“不显式 override”
- 它不再映射到任何项目自管 thread-level persisted state

## 6. 一条维护规则

如果将来要新增设置，必须先被归类为且只归类为：

1. binding-wise next-turn settings
2. 只读诊断视图

在这个归类存在之前，该设置不得成为新的命令面或新的项目持久化状态层。
