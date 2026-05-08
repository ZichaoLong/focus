# 飞书帮助导航合同

英文原文：`docs/contracts/feishu-help-navigation.md`

本文只定义 `/help` 与 `/commands` 相关的导航合同。

它回答：

- `/help` 要暴露哪些主题页
- 每个主题页要解决什么问题
- 哪些命令刻意不走主导航

## 1. 目标

`/help` 不是第二套完整文档，也不是所有命令的平铺清单。

它的目标是渐进披露：

1. 先按用户眼前要解决的问题分组
2. 再通过按钮或表单进入对应操作
3. 把高级恢复 / 调试动作留给结果卡或纯文字命令

## 2. 根导航

`/help` 根卡固定暴露五个主题：

- `当前会话`
- `群聊`
- `线程`
- `运行时`
- `身份`

它们对应的关注点分别是：

- `当前会话`
  - `/status`
  - `/preflight`
  - `/cd`
- `群聊`
  - `/group`
  - `/group-mode`
  - 群聊协作边界
- `线程`
  - `/threads`
  - `/new`
  - `/resume`
  - 当前线程页
- `运行时`
  - `/permissions`
  - `/approval`
  - `/sandbox`
  - `/collab-mode`
  - `/reset-backend`
- `身份`
  - `/whoami`
  - `/bot-status`
  - `/init`

## 3. 子页合同

### 3.1 当前会话

必须提供：

- `/status` 按钮
- `/preflight` 按钮
- 一个动态推送切换动作
- `/cd` 表单入口

不要求暴露 `/pwd`。

这个推送切换动作必须跟随当前 binding 状态：

- 当前 binding 为 `attached` 时显示 `/detach`
- 当前 binding 为 `detached` 时显示 `/attach`

### 3.2 线程

必须提供：

- `/threads`
- `/new`
- `/resume` 表单
- `当前线程` 二级页

### 3.3 当前线程

必须提供：

- `/profile`
- `/memory`
- `/archive`
- `重命名` 表单入口

并且正文里要明确：

- 推送开关属于“当前会话”页
- 如果只是为了 re-profile，应优先走 `/profile`
- 本地高级排障可用 `feishu-codexctl thread detach --thread-id <thread_id>`

### 3.4 运行时

必须提供：

- `/permissions`
- `/approval`
- `/sandbox`
- `/collab-mode`
- `/reset-backend`

并且正文里要明确：

- reset 完成后，如需继续收到推送，可使用 `/attach [binding|thread|service]`
- 更常见的入口是 reset 结果卡里的 attach 按钮

### 3.5 身份

必须提供：

- `/whoami`
- `/bot-status`
- `/init` 表单入口

并明确：

- `/whoami` 和 `/init` 只支持私聊

## 4. `/commands` 的角色

`/commands` 是纯文字命令索引。

它的责任是：

- 用文字列出常用命令
- 与 `/help` 的分组保持一致

它不是：

- 第二套导航卡
- 所有调试命令的穷举列表

## 5. 刻意不走主导航的命令

下列命令当前不要求从 `/help` 根导航直达：

- `/commands`
- `/h`
- `/pwd`
- `/cancel`
- `/attach`
- `/debug-contact`

原因：

- `/commands` 与 `/h` 属于索引 / 别名
- `/pwd` 已被无参数 `/cd` 弱化
- `/cancel` 的主入口是执行卡按钮
- `/attach` 属于恢复面，更适合由 reset 结果卡给出
- `/debug-contact` 是管理员排障命令

虽然 `/detach` 与 `/attach` 都不是根导航命令，但“当前会话”页必须把这个会话级推送切换动作显式给出来。

## 6. 按钮权限

帮助卡本身允许在群里被翻页查看，但真正会变更状态的按钮 / 表单提交，仍必须在后续命令处理层执行权限检查。

也就是说：

- 导航可被非管理员看到并不等于可越权执行
- slash 命令与卡片动作的最终权限判定，必须以后端命令处理为准

如果新增、删除、改名任何帮助页、按钮或表单入口，本文必须同步更新。
