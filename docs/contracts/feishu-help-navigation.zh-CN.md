# 飞书帮助导航合同

英文原文：`docs/contracts/feishu-help-navigation.md`

本文只定义 `/help` 与 `/commands` 相关的导航合同。

它回答：

- `/help` 首页要暴露什么
- 各工作区页分别负责什么
- 哪些命令刻意不放到工作台首页

## 1. 目标

`/help` 不是第二套完整文档，也不是所有命令的平铺清单。

它的目标仍然是渐进披露：

1. 先给出当前工作状态摘要
2. 再按用户要做的事进入固定工作区
3. 把低频高级动作留在下级页或结果卡，不强行塞进首页

## 2. 根导航

`/help` 根卡现在是“工作台”，不是五主题目录。

它必须同时包含两部分：

- 状态摘要
- 六个固定工作区

### 2.1 首页状态摘要

首页状态摘要至少要覆盖：

- 当前目录
- 当前线程
- 当前 push 状态
- 本轮设置摘要

本轮设置摘要必须使用显式标签格式：

- `权限 <值> | 模型 <值> | 推理 <值>`
- 只有在 plan 模式启用时，才额外附加 `| Plan模式`

在群聊上下文中，如果能安全读取群状态，还应额外显示：

- 当前群是否已启用
- 当前群工作模式

### 2.2 固定工作区

首页固定暴露六个工作区：

- `开始`
- `线程设置`
- `本轮设置`
- `连接状态`
- `群聊设置`
- `更多`

首页本身不承载：

- 动态建议操作
- 意图搜索
- 低频诊断表单

### 2.3 直接 topic 入口

当前直接支持：

- `/help`
- `/help overview`
- `/help start`
- `/help thread-settings`
- `/help turn`
- `/help connection`
- `/help group`
- `/help more`

为了兼容旧入口，以下 alias 仍然有效：

- `chat`
- `thread`
- `runtime`
- `identity`

## 3. 页面合同

### 3.1 返回按钮规则

- 一级工作区页必须提供 `返回首页`
- 下级页只保留 `返回上一页`
- 所有返回按钮都必须独占一整行

### 3.2 开始

负责：

- `/new`
- `/threads`
- `/resume` 表单
- `/cd` 表单

正文里还必须明确：

- 同一线程允许多端订阅观察，但 live turn 只有一个交互 owner
- 本地继续同一 live thread 用 `fcodex resume <thread_id|thread_name>`
- 本地查看当前目录线程用 `feishu-codexctl thread list --scope cwd`

### 3.3 线程设置

必须提供：

- `/profile`
- `/memory`
- `/compact`
- `/archive`
- `重命名` 表单
- `按目标归档` 表单

正文里还必须明确：

- 新建、恢复、浏览线程与切目录不在这里，而在“开始”
- 如果只是为了 re-profile，优先直接走 `/profile <name>`
- 如果只是为了切 memory mode，优先直接走 `/memory <off|read|read_write>`

### 3.4 本轮设置

必须提供：

- `/permissions`
- `/model`
- `/effort`
- `/approval`
- `/sandbox`
- `/collab-mode`

正文里还必须明确：

- 推荐先用 `/permissions`
- 这些设置作用于当前飞书会话后续 turn
- 实例级 backend reset 不在这里，而在“更多 -> 高级操作”

### 3.5 连接状态

必须提供：

- `/status`
- `/preflight`
- 一个动态 push 开关
- `/attach service`
- `更多附着方式` 下级页

动态 push 开关必须跟随当前 binding 状态：

- 当前 binding 为 `attached` 时显示“暂停推送”，执行 `/detach`
- 当前 binding 为 `detached` 时显示“恢复当前会话”，执行 `/attach`

`更多附着方式` 下级页必须提供：

- `/attach thread`
- `/attach`

### 3.6 群聊设置

必须提供：

- `/group`
- `/group activate`
- `/group deactivate`
- `/group-mode`

正文里还必须明确：

- 未启用群里，非管理员不能使用机器人
- `all` 风险最高
- 所有共享状态变更仍以后端权限检查为准

### 3.7 更多

必须提供：

- `/whoami`
- `/bot-status`
- `/commands`
- `初始化` 表单
- `高级操作` 下级页

正文里还必须明确：

- `/whoami` 与 `/init` 只支持私聊

`高级操作` 下级页必须提供：

- `/reset-backend`
- `联系人排障` 表单

`联系人排障` 表单提交后等价于：

- `/debug-contact <open_id>`

## 4. `/commands` 的角色

`/commands` 是纯文字命令索引。

它的责任是：

- 用文字列出常用命令
- 与工作台分组保持一致

它不是：

- 第二套导航卡
- 所有调试命令的穷举列表

## 5. 刻意不放到工作台首页的命令

下列命令当前不要求作为首页固定工作区入口直接出现：

- `/help`
- `/h`
- `/pwd`
- `/cancel`

原因：

- `/help` 与 `/h` 本身就是入口
- `/pwd` 已被无参数 `/cd` 弱化
- `/cancel` 的主入口仍是执行卡按钮

注意：

- `/commands` 现在可从“更多”进入
- `/attach` 现在可从“连接状态”进入
- `/debug-contact` 现在可从“更多 -> 高级操作”进入

## 6. 按钮权限

帮助卡本身允许在群里被翻页查看，但真正会变更状态的按钮 / 表单提交，仍必须在后续命令处理层执行权限检查。

也就是说：

- 导航可见不等于有权执行
- slash 命令与卡片动作的最终权限判定，必须以后端命令处理为准

如果新增、删除、改名任何帮助页、按钮或表单入口，或改变 `/help` 工作区归属与可达性，本文必须同步更新。
