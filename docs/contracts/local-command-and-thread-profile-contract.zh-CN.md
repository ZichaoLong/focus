# 本地命令与运行时设置合同

英文原文：`docs/contracts/local-command-and-thread-profile-contract.md`

说明：本文件沿用历史文件名，但当前重点已经不是“thread profile”，而是本地入口与现行设置模型的边界。

## 1. 三个本地入口

### 1.1 `feishu-codex`

负责：

- 安装与升级
- service 生命周期
- 实例管理
- 项目级辅助动作

### 1.2 `feishu-codexctl`

负责：

- 查看实例 / binding / thread / service 状态
- 执行有限的本地管理动作
- 排查 attach / detach / backend 问题

它不是：

- 飞书 `/memory` 的替代面
- 第二个 turn-setting 前端

### 1.3 `fcodex`

负责：

- 进入本地 Codex TUI
- 恢复或接入某条 live thread
- 作为本地 frontend 连接实例 backend

它不是：

- service 管理 CLI
- 飞书设置卡片的本地镜像

## 2. 当前只保留两类项目设置

### 2.1 实例 startup baseline

- 作用对象：实例
- 飞书入口：`/profile`、`/profile-clear`
- 本地语义：修改实例 backend 的启动基线

### 2.2 binding-wise next-turn settings

- 作用对象：飞书 binding
- 飞书入口：`/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode`
- 本地 `fcodex` / 上游 TUI 有自己的本地状态，不与飞书 binding 持久化自动合并

## 3. 已移除的本地 thread-memory 合同

当前不再支持：

- `feishu-codexctl thread memory`
- 项目自管的 thread-memory 恢复语义
- `fcodex resume <thread>` 额外吃入一份本项目持久化 memory 设置

如果用户希望切换 memory/provider，应通过：

- 实例 startup profile
- 上游 config / profile-v2

## 4. `fcodex -p/--profile` 的当前定位

本项目不再把 `fcodex -p/--profile` 当成 thread-wise 持久化改写入口。

当前它的定位是：

- 上游 / 本地 TUI 侧参数
- 不是飞书 `/profile` 的本地镜像
- 不会被本项目持久化成 thread 级事实源

## 5. `fcodex resume` 现在稳定承诺什么

`fcodex resume <thread_id|thread_name>` 当前承诺：

- thread 身份解析
- live runtime owner / loaded gate fail-close
- 连接到正确实例 backend

它不再承诺：

- 恢复本项目自管的 thread memory/provider slice

## 6. 一条维护规则

如果某个新设置要进入本项目，必须先归类为：

1. 实例 startup baseline
2. binding-wise next-turn settings
3. 只读诊断视图

在完成归类之前，不应新增本地命令面。
