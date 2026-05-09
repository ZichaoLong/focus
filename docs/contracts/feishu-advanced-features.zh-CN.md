# 飞书侧 Codex 高级功能合同

英文原文：`docs/contracts/feishu-advanced-features.md`

本文定义飞书侧当前正式暴露的三类上游 Codex 高级能力：

- `compact`
- `skills`
- `plugins`

它回答：

- 每个能力作用在哪一层状态
- 哪些会立即改变当前 thread，哪些只影响后续 turn
- 飞书侧刻意不支持哪些上游能力

## 1. 目标

飞书侧不复刻上游 TUI 的全部高级界面。

当前合同只提供：

- 用户在飞书里真正能理解的最小闭环
- 与当前项目状态层一致的入口
- 明确的“支持什么 / 不支持什么”边界

## 2. `/compact`

`/compact` 是 **当前绑定 thread** 的显式动作。

它的合同是：

- 只作用于当前绑定 thread
- 不接受额外参数
- 执行中不能触发
- 如果当前没有绑定 thread，明确拒绝
- 如果当前 thread 尚未 load 到本实例 backend，明确拒绝，并提示先 `/attach` 或直接发送一条普通消息恢复

飞书侧 **不会** 为了执行 `/compact` 隐式做 attach / resume。

原因：

- `compact` 是 thread 级显式压缩动作
- 不应偷偷改变当前 Feishu runtime / backend 装载状态
- fail-closed 比“顺手帮你恢复一些别的状态”更清楚

## 3. `/skills`

`/skills` 作用于 **当前目录可见的 skills 配置面**。

它的合同是：

- 展示当前目录可见的 skills
- 展示每个 skill 的作用域、路径、启用状态
- 允许启用 / 禁用 skill
- 启停结果对后续 turn 生效

它不是：

- thread 私有设置
- backend reset 入口
- skill 安装 / 卸载入口

当前实现刻意总是按当前目录 force-reload skills 列表，以保证飞书侧看到的是接近磁盘事实的结果。

## 4. `/plugins`

`/plugins` 作用于 **当前目录可见的 plugins 配置与可见性面**。

它的合同分两层：

### 4.1 `/plugins`

无参数 `/plugins` 必须提供：

- 当前目录可见 marketplaces 概览
- 当前目录下可见的已安装 plugins 概览
- 可复制 / 可引用的 `plugin_id`

### 4.2 `/plugins <plugin_id>`

带参数时必须提供：

- 指定 plugin 的详情
- 是否已安装 / 是否已启用
- 关联 skills / hooks / apps / MCP server 摘要

如果该 plugin 已安装，则允许：

- 启用
- 禁用

这些变化对后续 turn 生效。

## 5. 刻意不支持的插件能力

飞书侧当前 **不** 提供：

- plugin 安装
- plugin 卸载
- marketplace 增删改
- plugin share
- auth 驱动流程

原因：

- 这些动作副作用重
- 状态层复杂
- 不适合进入日常飞书命令主流程

## 6. agents / subagents

飞书侧当前不提供 agents / subagents 观察页或控制页。

原因不是“上游没有这个概念”，而是：

- 当前 app-server 正式请求面没有一个与飞书卡片天然匹配的稳定 agent 观察接口
- 强行把子代理状态揉进当前执行卡，会显著增加维护复杂度

因此当前正式合同是：

- 自然语言仍可触发模型按上游工具合同使用 subagent
- 飞书侧暂不单独暴露 agents 命令面

## 7. 帮助导航位置

这三类能力在飞书导航中的正式位置是：

- `/compact`
  - `线程 -> 当前线程`
- `/skills`
  - `高级功能`
- `/plugins`
  - `高级功能`

如果后续新增、删除、改名这些高级能力命令，或改变其状态层、帮助页归属、支持边界，本文必须同步更新。
