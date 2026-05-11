# 飞书命令矩阵

英文原文：`docs/contracts/feishu-command-matrix.md`

本文是飞书侧一等命令面的事实表。

它只回答四件事：

- 当前有哪些正式支持的 slash 命令
- 哪些命令能从 `/help` 导航到达
- 私聊 / 群聊里谁可以执行
- 它们分别对应哪个本地入口

不在这里重复解释的内容：

- binding / attach / detach / backend 的底层状态语义
- thread-wise profile 何时可写
- 群聊 `assistant / mention-only / all` 的完整群合同

这些分别以相关专题合同为准。

## 1. 读法

- “可从 `/help` 到达”指可通过帮助卡按钮、表单或后续结果卡进入。
- “仅管理员”指必须通过当前机器人的管理员判定。
- “任何人”只表示该上下文不要求管理员，不代表所有群成员都能改共享状态。

## 2. 命令表

### 2.1 导航、会话、线程

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/help [chat\|group\|thread\|runtime\|advanced\|identity]` | 打开帮助导航或指定页 | 是 | 仅管理员 | 仅管理员 | 无直接对应 |
| `/commands` | 纯文字列出常用命令 | 否 | 仅管理员 | 仅管理员 | 无 |
| `/h` | `/help` 别名 | 否 | 仅管理员 | 仅管理员 | 无 |
| `/pwd` | 查看当前目录 | 否 | 仅管理员 | 仅管理员 | 无 |
| `/status` | 查看当前 chat 的目录、当前线程与当前会话设置摘要 | 是；`chat` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl binding status <binding_id>` 可看更细诊断 |
| `/preflight` | dry-run 下一条普通消息与当前 chat 的 detach 可用性 | 是；`chat` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl binding status <binding_id>` 部分覆盖 |
| `/cd [path]` | 查看或切换当前目录；切目录会清空当前线程绑定 | 是；`chat` 页表单 | 仅管理员 | 仅管理员 | 无 |
| `/new` | 新建当前线程 | 是；`thread` 页 | 仅管理员 | 仅管理员 | 无 |
| `/threads` | 浏览当前目录线程 | 是；`thread` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl thread list --scope cwd` |
| `/resume <thread_id\|thread_name>` | 恢复目标线程到当前 chat | 是；`thread` 页表单 | 仅管理员 | 仅管理员 | 本地继续 live thread 应使用 `fcodex resume <thread_id\|thread_name>` |
| `/profile [name]` | 查看或切换当前 thread 的 thread-wise profile | 是；`thread -> 当前线程` | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/memory [off\|read\|read_write]` | 查看或切换当前 thread 的 thread-wise memory mode | 是；`thread -> 当前线程` | 仅管理员 | 仅管理员 | `feishu-codexctl thread memory --thread-id/--thread-name`；`fcodex resume` 会沿用已持久化模式 |
| `/compact` | 压缩当前绑定 thread 的上下文历史 | 是；`thread -> 当前线程` | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/rename <title>` | 重命名当前 thread | 是；`thread -> 当前线程` 表单 | 仅管理员 | 仅管理员 | 无 |
| `/archive [thread_id\|thread_name]` | 归档当前 thread，或按目标归档 | 是；`thread -> 当前线程` | 仅管理员 | 仅管理员 | `feishu-codexctl thread archive --thread-id/--thread-name` |
| `/detach` | 让当前 chat 暂停接收当前 thread 的飞书推送；保留 binding bookmark | 否；仅在 `chat -> 当前会话` 页作为按钮曝光 | 仅管理员 | 仅管理员 | `feishu-codexctl binding detach <binding_id>`；thread 级是 `feishu-codexctl thread detach ...` |
| `/attach [binding\|thread\|service]` | 恢复当前 chat、当前 thread 或当前实例的飞书推送 | 否；高级恢复面，主入口通常是 reset 结果卡按钮 | 仅管理员 | 仅管理员 | `feishu-codexctl binding/thread/service attach ...` |
| `/cancel` | 取消当前执行 | 否；主入口是执行卡按钮 | 仅管理员 | 仅管理员 | 无 |

### 2.2 运行时、高级功能与身份

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/reset-backend` | 预览并重置当前实例 backend | 是；`runtime` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl service reset-backend` |
| `/permissions [read-only\|default\|full-access]` | 同时设置审批策略与沙箱策略 | 是；`runtime` 页 | 仅管理员 | 仅管理员 | 无 |
| `/model [name\|auto]` | 设置当前飞书会话后续 turn 的 model override | 是；`runtime` 页 | 仅管理员 | 仅管理员 | 无 |
| `/approval [untrusted\|on-request\|never]` | 设置审批策略 | 是；`runtime` 页 | 仅管理员 | 仅管理员 | 无 |
| `/sandbox [read-only\|workspace-write\|danger-full-access]` | 设置沙箱策略 | 是；`runtime` 页 | 仅管理员 | 仅管理员 | 无 |
| `/collab-mode [default\|plan]` | 设置当前飞书会话后续 turn 的协作模式 | 是；`runtime` 页 | 仅管理员 | 仅管理员 | 无 |
| `/skills` | 查看当前目录可见的 skills，并启用或禁用 | 是；`advanced` 页 | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/plugins [plugin_id]` | 查看当前目录可见的 plugins；带 `plugin_id` 时查看详情 | 是；`advanced` 页 | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/whoami` | 查看自己的身份信息 | 是；`identity` 页 | 任何人 | 不支持 | 无 |
| `/bot-status` | 查看机器人身份与配置探测结果 | 是；`identity` 页 | 任何人 | 仅管理员 | 无 |
| `/init <token>` | 初始化管理员与 `bot_open_id` | 是；`identity` 页表单 | 任何人 | 不支持 | `feishu-codex config init-token` 只负责查看 token |
| `/debug-contact <open_id>` | 排查通讯录名字解析问题 | 否 | 仅管理员 | 不支持 | 无 |

### 2.3 群聊专属

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/group` | 查看当前群是否已激活 | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group activate` | 激活当前群 | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group deactivate` | 停用当前群 | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode` | 查看当前群聊工作态 | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode assistant` | 切到 `assistant` | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode mention-only` | 切到 `mention-only` | 是；`group` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode all` | 切到 `all` | 是；`group` 页 | 不支持 | 仅管理员 | 无 |

## 3. 刻意不做主导航入口的命令

下列命令保留为文字入口或结果卡入口，不做 `/help` 根导航主路径：

- `/commands`
- `/h`
- `/pwd`
- `/cancel`
- `/attach`
- `/debug-contact`

`/detach` 也不是根导航命令，但会在“当前会话”页以按钮形式暴露，因为它仍然是可理解的会话级推送开关。

## 4. 结果卡按钮

下列按钮属于正式支持的飞书侧用户入口，必须和 slash 命令一起维护：

- 执行卡：`取消执行`
- `/threads` 列表卡：`恢复/当前`、`归档`、`更多`、`收起`
- `/profile` / `/memory` / `/reset-backend` 结果卡：`应用并重置 backend`、`强制应用并重置 backend`、`附着当前线程`、`附着当前实例`、`保持 detached`
- `/model` / `/permissions` / `/approval` / `/sandbox` / `/collab-mode` 卡：turn-time runtime setting 切换按钮
- `/skills` / `/plugins` 卡：skill 启停、plugin 详情返回、已安装 plugin 启停
- 审批 / 补充输入卡：按当前请求类型暴露 `允许/拒绝/提交` 等按钮

## 5. 边界

- `feishu-codex` 负责安装、实例、service 生命周期，不是飞书会话命令面。
- `feishu-codexctl` 负责本地查看 / 管理 binding、thread、service，不是第二个前端。
- `fcodex` 才是本地继续 live thread 的入口。

如果新增、删除、改名任何飞书命令，或改变 `/help` 可达性、按钮入口、权限边界，必须同步更新本文。
