# 飞书 `/help` 导航合同

英文原文：`docs/contracts/feishu-help-navigation.md`

本文只定义 `/help` 与 `/commands` 的导航合同。

## 1. 首页目标

`/help` 不是完整文档站，也不是把所有命令平铺出来。

它的职责是：

1. 先给出紧凑的当前状态摘要
2. 再把用户送到固定工作区
3. 低频动作放到下级页或结果卡

## 2. 首页固定工作区

首页必须暴露这六个工作区：

- `开始`
- `线程设置`
- `本轮设置`
- `连接状态`
- `群聊设置`
- `更多`

首页摘要至少包含：

- 当前目录
- 当前线程
- 当前推送状态
- 当前本轮设置摘要

## 3. 页面合同

### 3.1 开始

负责：

- `/new`
- `/threads`
- `/resume`
- `/cd`

正文应提示：

- 同一 thread 可多端观察，但 live turn 只有一个 interaction owner
- 本地继续同一 live thread 用 `fcodex resume <thread_id|thread_name>`

### 3.2 线程设置

负责：

- `/goal`
- `/profile`
- `/compact`
- `/archive`
- 重命名表单

正文应提示：

- `/profile` 管的是实例 startup profile
- 新建、恢复、浏览线程在“开始”
- 这里不再提供 thread-wise memory 控制面

### 3.3 本轮设置

负责：

- `/permissions`
- `/model`
- `/effort`
- `/approval`
- `/collab-mode`
- `/last text`

正文应提示：

- 这些设置作用于当前飞书会话后续 turn
- 推荐先用 `/permissions`

### 3.4 连接状态

负责：

- `/status`
- `/preflight`
- `/detach`
- `/attach`
- 相关附着下级页

### 3.5 群聊设置

负责：

- `/group`
- `/group activate`
- `/group deactivate`
- `/group-mode`

### 3.6 更多

负责：

- `/commands`
- `/whoami`
- `/bot-status`
- `/init`
- `/reset-backend`
- `/debug-contact`

## 4. 返回按钮规则

- 一级工作区页必须提供 `返回首页`
- 下级页只保留 `返回上一页`
- 返回按钮独占一整行

## 5. 兼容入口

以下直接主题入口仍需兼容：

- `/help`
- `/help overview`
- `/help start`
- `/help thread-settings`
- `/help turn`
- `/help connection`
- `/help group`
- `/help more`

以下旧 alias 仍需兼容：

- `chat`
- `thread`
- `runtime`
- `identity`
