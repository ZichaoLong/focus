# 本地命令与运行时设置合同

英文原文：`docs/contracts/local-command-and-thread-profile-contract.md`

本文件保留历史文件名，但已不再定义任何项目自管 `profile` 面。它现在定义本地
入口与剩余设置模型之间的边界。

## 1. 三个本地入口

### 1.1 `feishu-codex`

负责：

- 安装与升级
- service 生命周期
- 实例管理
- 项目级辅助动作

### 1.2 `feishu-codexctl`

负责：

- 查看 instance / binding / thread / service 状态
- 执行有限的本地管理动作
- 诊断 attach / detach / backend 问题

它不是：

- turn settings 的第二前端
- 飞书设置卡片的本地镜像

### 1.3 `fcodex`

负责：

- 进入本地 Codex TUI
- 恢复或接入 live thread
- 作为实例 backend 的本地前端

它不是：

- service-management CLI
- 项目自管设置面

## 2. 只剩一个项目自管可写设置族

### 2.1 binding-wise next-turn settings

- scope：Feishu binding
- 飞书入口：`/model`、`/effort`、`/approval`、`/permissions`
- 本地 `fcodex` / 上游 TUI 仍保持各自本地状态，不会自动与飞书侧持久化 binding 设置合并

## 3. 已移除的项目自管设置

本项目已不再支持：

- 历史上的项目自管 profile 命令
- `/memory`
- `feishu-codexctl thread memory`
- 任何项目自管的 thread-memory / provider restore 语义

如果操作者想使用上游 profile/provider 行为，应直接使用上游 Codex 配置、
上游 profile-v2 文件，或上游启动参数。

## 4. `fcodex -p/--profile` 的当前含义

本项目不再把 `fcodex -p/--profile` 视为持久化写入口。

它现在只是：

- 上游 / 本地 TUI 的启动参数
- 不是任何飞书命令的本地镜像
- 不是本项目持久化成 thread truth 的东西

## 5. `fcodex resume` 仍承诺什么

`fcodex resume <thread_id|thread_name>` 现在仍承诺：

- thread identity 解析
- live-runtime-owner / loaded-gate fail-close 行为
- 接到正确的实例 backend

它不再承诺：

- 恢复项目自管的 profile slice
- 恢复项目自管的 memory/provider slice

## 6. 一条维护规则

如果以后本项目要引入一个新设置，必须先被归类为且只归类为：

1. binding-wise next-turn settings
2. 只读诊断视图

在这个归类存在之前，本项目不得为它新增本地命令面。
