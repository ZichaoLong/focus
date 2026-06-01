# Thread Next-Load Settings 语义

英文原文：`docs/contracts/thread-next-load-settings-semantics.md`

本文保留原文件名，作为退役说明。

## 1. 当前结论

本项目现在**不再保留任何项目自管的 thread-wise next-load 设置**。

也就是说，当前正式合同里已经没有：

- thread memory setting
- thread provider setting
- `new_thread_memory_mode_seed`
- 任何“先持久化到本项目，再在下次 resume 时额外注入”的 thread 级设置层

## 2. 现在由哪两层替代

### 2.1 实例 startup baseline

由 `/profile` / `/profile-clear` 管理。

它的语义是：

- 作用于实例 backend 的下次启动
- 不是 thread 真相

### 2.2 binding-wise next-turn settings

由：

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

管理。

它们的语义是：

- 作用于当前飞书会话后续 turn
- 主生效点是 `turn/start`
- 不是 thread 级持久化恢复设置

## 3. `resume` 的当前合同

本项目支持的恢复路径当前只承诺：

- 做 thread 身份解析与安全准入
- 恢复到正确实例 backend
- 保留实例级 startup baseline 与当前 frontend 自己的运行时语义

它不再承诺：

- 为某个 thread 额外恢复一份本项目持久化的 memory/provider 设置

## 4. 为什么保留这个文件

因为“thread-wise next-load 设置”这个概念本身仍然重要：

- 它提醒维护者不要把实例基线、binding override、live runtime 诊断混为一谈

但在当前版本里，这一类设置的正式成员数是：

- `0`

## 5. 后续维护规则

如果将来要重新引入某个 thread-wise next-load 设置，必须先明确：

1. 写后持久源是什么
2. 正式生效边界是什么
3. 与实例 baseline、binding override 如何区分

在文档先收敛之前，不应直接恢复命令面。
