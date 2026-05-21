# 飞书命令矩阵

英文原文：`docs/contracts/feishu-command-matrix.md`

本文是飞书侧一等命令面的事实表。

它只回答四件事：

- 当前有哪些正式支持的 slash 命令
- 哪些命令能从 `/help` 工作台到达
- 私聊 / 群聊里谁可以执行
- 它们分别对应哪个本地入口

不在这里重复解释的内容：

- binding / attach / detach / backend 的底层状态语义
- thread-wise profile 何时可写
- 群聊 `assistant / mention-only / all` 的完整群合同

## 1. 读法

- “可从 `/help` 到达”指可通过工作台按钮、表单或后续结果卡进入。
- “仅管理员”指必须通过当前机器人的管理员判定。
- “任何人”只表示该上下文不要求管理员，不代表所有群成员都能改共享状态。

## 2. 命令表

### 2.1 导航、开始、线程设置、连接状态

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/help [overview\|start\|thread-settings\|turn\|connection\|group\|more]` | 打开工作台或指定工作区；兼容旧 alias `chat/thread/runtime/identity` | 是 | 仅管理员 | 仅管理员 | 无直接对应 |
| `/commands` | 纯文字列出常用命令 | 是；`更多` 页 | 仅管理员 | 仅管理员 | 无 |
| `/h` | `/help` 别名 | 否 | 仅管理员 | 仅管理员 | 无 |
| `/pwd` | 查看当前目录 | 否 | 仅管理员 | 仅管理员 | 无 |
| `/status` | 查看当前 chat 的目录、当前线程与当前会话设置摘要 | 是；`连接状态` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl binding status <binding_id>` 可看更细诊断 |
| `/preflight` | dry-run 下一条普通消息与当前 chat 的 detach 可用性 | 是；`连接状态` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl binding status <binding_id>` 部分覆盖 |
| `/cd [path]` | 查看或切换当前目录；切目录会清空当前线程绑定 | 是；`开始` 页表单 | 仅管理员 | 仅管理员 | 无 |
| `/new` | 新建当前线程 | 是；`开始` 页 | 仅管理员 | 仅管理员 | 无 |
| `/threads` | 浏览当前目录线程 | 是；`开始` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl thread list --scope cwd` |
| `/resume <thread_id\|thread_name>` | 恢复目标线程到当前 chat | 是；`开始` 页表单 | 仅管理员 | 仅管理员 | 本地继续 live thread 应使用 `fcodex resume <thread_id\|thread_name>` |
| `/goal [show\|set <objective>\|pause\|resume\|clear]` | 查看或管理当前 thread 的 goal | 是；`线程设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/profile [name]` | 查看或切换当前 thread 的 thread-wise profile | 是；`线程设置` 页 | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/memory [off\|read\|read_write]` | 查看或切换当前 thread 的 thread-wise memory mode | 是；`线程设置` 页 | 仅管理员 | 仅管理员 | `feishu-codexctl thread memory --thread-id/--thread-name`；`fcodex resume` 会沿用已持久化模式 |
| `/compact` | 压缩当前绑定 thread 的上下文历史 | 是；`线程设置` 页 | 仅管理员 | 仅管理员 | 无直接本地等价命令 |
| `/rename <title>` | 重命名当前 thread | 是；`线程设置` 页表单 | 仅管理员 | 仅管理员 | 无 |
| `/archive [thread_id\|thread_name]` | 归档当前 thread，或按目标归档 | 是；`线程设置` 页按钮或表单 | 仅管理员 | 仅管理员 | `feishu-codexctl thread archive --thread-id/--thread-name` |
| `/detach` | 让当前 chat 暂停接收当前 thread 的飞书推送；保留 binding bookmark | 是；`连接状态` 页动态按钮 | 仅管理员 | 仅管理员 | `feishu-codexctl binding detach <binding_id>`；thread 级是 `feishu-codexctl thread detach ...` |
| `/attach [binding\|thread\|service]` | 恢复当前 chat、当前 thread 或当前实例的飞书推送 | 是；`连接状态` 页及其下级页，结果卡也会给出上下文化入口 | 仅管理员 | 仅管理员 | `feishu-codexctl binding/thread/service attach ...` |
| `/cancel` | 取消当前执行 | 否；主入口是执行卡按钮 | 仅管理员 | 仅管理员 | 无 |

### 2.2 本轮设置与更多

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/permissions [read-only\|default\|full-access]` | 同时设置审批策略与沙箱策略 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/model [name\|auto]` | 设置当前飞书会话后续 turn 的 model override；无参数时打开 model/effort 联合卡片 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/effort [auto\|none\|minimal\|low\|medium\|high\|xhigh]` | 设置当前飞书会话后续 turn 的 effort override；无参数时打开 model/effort 联合卡片 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/approval [untrusted\|on-request\|never]` | 设置审批策略 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/sandbox [read-only\|workspace-write\|danger-full-access]` | 设置沙箱策略 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/collab-mode [default\|plan]` | 设置当前飞书会话后续 turn 的协作模式 | 是；`本轮设置` 页 | 仅管理员 | 仅管理员 | 无 |
| `/reset-backend` | 预览并重置当前实例 backend | 是；`更多 -> 高级操作` | 仅管理员 | 仅管理员 | `feishu-codexctl service reset-backend` |
| `/whoami` | 查看自己的身份信息 | 是；`更多` 页 | 任何人 | 不支持 | 无 |
| `/bot-status` | 查看机器人身份与配置探测结果 | 是；`更多` 页 | 任何人 | 仅管理员 | 无 |
| `/init <token>` | 初始化管理员与 `bot_open_id` | 是；`更多` 页表单 | 任何人 | 不支持 | `feishu-codex config init-token` 只负责查看 token |
| `/debug-contact <open_id>` | 排查通讯录名字解析问题 | 是；`更多 -> 高级操作` 表单 | 仅管理员 | 不支持 | 无 |

### 2.3 群聊设置

| 命令 | 作用 | `/help` 可达 | 私聊 | 群聊 | 本地对应 |
| --- | --- | --- | --- | --- | --- |
| `/group` | 查看当前群是否已激活 | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group activate` | 激活当前群 | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group deactivate` | 停用当前群 | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode` | 查看当前群聊工作态 | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode assistant` | 切到 `assistant` | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode mention-only` | 切到 `mention-only` | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |
| `/group-mode all` | 切到 `all` | 是；`群聊设置` 页 | 不支持 | 仅管理员 | 无 |

## 3. 刻意不做工作台首页入口的命令

下列命令保留为别名、文字入口或结果卡入口，不做首页固定工作区按钮：

- `/h`
- `/pwd`
- `/cancel`

额外说明：

- `/commands` 现在可从“更多”进入
- `/attach` 现在可从“连接状态”进入
- `/debug-contact` 现在可从“更多 -> 高级操作”进入

## 4. 结果卡按钮

下列按钮属于正式支持的飞书侧用户入口，必须和 slash 命令一起维护：

- 执行卡：`取消执行`
- `/threads` 列表卡：`恢复/当前`、`归档`、`更多`、`收起`
- `/goal` 卡：`刷新`、`暂停` / `恢复`、`清除`
- `/profile` / `/memory` / `/reset-backend` 结果卡：`应用并重置 backend`、`强制应用并重置 backend`、`附着当前线程`、`附着当前实例`、`保持 detached`
- `/model` / `/effort` 联合卡，以及 `/permissions` / `/approval` / `/sandbox` / `/collab-mode` 卡：turn-time runtime setting 切换按钮
- 审批 / 补充输入卡：按当前请求类型暴露 `允许/拒绝/提交` 等按钮

## 5. 边界

- `feishu-codex` 负责安装、实例、service 生命周期，不是飞书会话命令面。
- `feishu-codexctl` 负责本地查看 / 管理 binding、thread、service，不是第二个前端。
- `fcodex` 才是本地继续 live thread 的入口。

如果新增、删除、改名任何飞书命令，或改变 `/help` 可达性、按钮入口、权限边界，必须同步更新本文。
