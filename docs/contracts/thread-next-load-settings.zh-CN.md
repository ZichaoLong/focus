# thread-owned next-load settings 合同

日期：2026-05-11

## 1. 范围

本文定义 `feishu-codex` 中这两类设置的正式产品语义：

- `profile`
- `memory`

它们都属于：

- `thread-owned next-load state`

## 2. 核心判断

`feishu-codex` 以 thread 为中心，而不是以当前 frontend、当前 cwd、当前 repo 为中心。

因此：

- 同一个 thread 下次再 load 时，应继续使用它自己的 `profile` / `memory`
- 这两类设置不应跟着当前 frontend 漂移
- 也不应在 resume 时重新按当前 cwd / 当前配置环境重新推导

## 3. 正式持久化对象

只有：

- `materialized logical thread`

才拥有正式的 thread-wise persist state。

这里的“正式 persist state”包括：

1. `profile` slice
   - `profile`
   - `model`
   - `model_provider`
2. `memory` slice
   - `off`
   - `read`
   - `read_write`

## 4. provisional 合同

upstream `thread/start` 返回的 provisional shell：

- 不是正式的 materialized logical thread
- 不能直接拥有正式 thread-wise persist state

在 provisional 阶段，只允许存在：

- `pending seed`

不允许：

- 把 provisional shell 直接当成正式 thread store owner

## 5. promote 规则

当一个 provisional logical thread 完成首个成功用户 turn 后：

- pending seed promote 为正式 thread-wise persist state

在此之前：

- 它只是 provisional continuity 上的待晋升设置

## 6. abandon / replacement 规则

若 provisional thread 没有 materialize 就被放弃：

- 不写正式 thread-wise store

若 reset backend 后发生 provisional replacement：

- 迁移的是 logical continuity 上的 pending seed
- 不是把旧 provisional thread id 当成正式 owner

## 7. loaded thread 合同

当 thread 已 load：

- 当前这次 load 使用的是 `load-time observed snapshot`

因此：

- `profile` / `memory` 的 thread-wise 变更，默认只影响下次 load
- 不承诺热更新当前已 load thread 的运行态

若用户希望立即生效：

- 必须让该 thread 重新进入新的 load 周期
- 必要时通过 reset backend 或显式 replacement 达成

## 8. 本项目的实现边界

本项目当前明确拥有：

- thread-owned next-load state 的产品合同
- pending seed 到正式 store 的 promote 时机
- 对 ambiguous lifecycle 的 fail-close 行为

本项目当前不承诺：

- provisional pending seed 的跨服务重启 durability
- 对当前已 load thread 的运行态热重写

## 9. 设计意图

本合同的目标是避免下面这些错误语义：

- “拿到 provisional thread id 就等于正式 thread 已存在”
- “reset 之后还能继续往旧壳写设置”
- “resume 时重新按当前 cwd / 当前 profile 定义算一遍 thread 设置”

本项目的单一事实源应是：

- thread 自己的 next-load state
- provisional 阶段的 pending seed
- materialize 后的正式 thread-wise persist state
