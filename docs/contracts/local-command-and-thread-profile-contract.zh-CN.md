# 本地命令与运行时设置合同

英文原文：`docs/contracts/local-command-and-thread-profile-contract.md`

说明：本文件沿用历史文件名，但当前重点已经不是“thread profile”，而是
本地入口与三类运行时设置之间的边界。

## 1. 三个本地入口

### 1.1 `feishu-codex`

负责：

- 安装与升级
- service 生命周期
- 实例管理
- 项目级辅助动作

不负责：

- 进入 Codex TUI
- 直接继续某条 live thread 的本地交互

### 1.2 `feishu-codexctl`

负责：

- 查看实例 / binding / thread / service 状态
- 做有限的本地管理动作
- 帮助排查 attach / detach / backend 问题

不负责：

- 持久化飞书侧 binding-wise next-turn 设置
- 充当第二个飞书前端

### 1.3 `fcodex`

负责：

- 进入本地 Codex TUI
- 恢复或接入某条 live thread
- 作为本地 frontend 与 backend 通信

它不是：

- 飞书命令面的镜像
- service 管理 CLI

## 2. 本项目当前三类设置

### 2.1 实例 startup profile

- 作用对象：managed backend 实例
- 飞书入口：`/profile`、`/profile-clear`
- 本地语义：修改实例启动基线，而不是某个 thread 的持久化恢复设置

当前没有一条与飞书 `/profile` 完全等价的本地 `fcodex` 命令。

### 2.2 thread-wise next-load memory

- 作用对象：thread
- 飞书入口：`/memory`
- 本地观察 / 管理：`feishu-codexctl thread memory ...`
- 本地恢复：`fcodex resume <thread>` 会沿用这份已持久化 memory mode

### 2.3 binding-wise next-turn 设置

- 作用对象：飞书 binding
- 飞书入口：`/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode`
- 本地 `fcodex` / 上游 TUI 有自己的本地状态，不与飞书 binding 持久化自动合并

## 3. `fcodex -p/--profile` 的当前定位

本项目不再把 `fcodex -p/--profile` 当成 thread-wise 持久化 profile 改写入口。

当前它的定位是：

- upstream / 本地 TUI 侧的启动提示或局部运行时提示
- 不是飞书 `/profile` 的本地镜像
- 不会在本项目里被持久化为 thread-wise next-load truth

因此：

- 飞书 `/profile` 改的是实例 startup baseline
- `fcodex -p/--profile` 改的是本地进入 TUI 时的上游侧提示

两者不再承诺同义。

## 4. `fcodex resume` 现在稳定承诺什么

`fcodex resume <thread_id|thread_name>` 现在仍正式承诺：

- 先解析 thread 身份
- 再按 live runtime owner / loaded gate 做 fail-close 路由
- 恢复时沿用该 thread 的持久化 memory mode

它不再正式承诺：

- 沿用某个本项目持久化的 thread-wise profile slice
- 借由 `-p/--profile` 改写 thread 的 next-load profile tuple

## 5. 与上游配置的关系

共享 `~/.codex/config.toml` 仍然是上游 `codex` / app-server 的用户配置来源。

但本项目的三类设置并不等于“把整个上游配置重新实现一遍”：

- startup profile：只控制 managed backend 的启动基线层
- thread memory：只控制本项目定义的 thread-wise memory 恢复语义
- binding settings：只控制飞书侧后续 turn 的 override

这三类设置都不意味着：

- 本项目会把上游所有配置字段都持久化成自己的 thread 事实源

## 6. 一条维护原则

如果某个新设置想进入本项目，必须先明确它属于哪一类：

1. 实例 startup baseline
2. thread-wise next-load state
3. binding-wise next-turn settings

在没有先归类之前，不应把它塞进 `/profile`、`/memory` 或现有 binding 设置里。
