# `feishu-codexctl` 命令矩阵

英文原文：`docs/contracts/feishu-codexctl-command-matrix.md`

本文定义本地 `feishu-codexctl` 管理面的正式命令面。

它只回答：

- `feishu-codexctl` 管哪些资源
- 哪些命令只读，哪些命令改状态
- 线程目标如何选择
- 它和飞书命令面如何对应

## 1. 总原则

- `feishu-codexctl` 是本地查看 / 管理面，不是第二个 Codex 前端。
- 想继续 live thread，用 `fcodex`。
- 想装服务、修服务、管理实例，用 `feishu-codex`。
- 想看 binding / thread / service 当前状态，或做本地 thread-scoped 管理，用 `feishu-codexctl`。

## 2. 实例与目标选择

- 除 `instance list` 外，其余命令都可加 `--instance <name>`。
- 显式 `--instance` 始终优先。
- 省略时按 `preferred-running -> unique-running -> default-running -> current-instance-paths` 规则解析。
- `thread status`、`thread bindings`、`thread archive`、`thread attach`、`thread detach` 必须二选一：
  - `--thread-id <id>`
  - `--thread-name <name>`

## 3. 资源层

`feishu-codexctl` 分六类资源：

- `instance`
- `service`
- `binding`
- `prompt`
- `thread`
- `image`

其中：

- `binding` 是 chat-scoped 视角
- `thread` 是 thread-scoped 视角

两者不要混读。

## 4. 命令表

### 4.1 `instance`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl instance list` | 列出本机当前运行中的实例、owner pid、control endpoint、app-server 地址 | 只读 | 无 |

### 4.2 `service`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] service status` | 查看目标实例 service / control plane / app-server 概况 | 只读 | 无一条完全等价命令 |
| `feishu-codexctl [--instance <name>] service reset-backend [--force]` | 重置当前实例 backend，但不重启 `feishu-codex` service | 变更 | 飞书 `/reset-backend` |
| `feishu-codexctl [--instance <name>] service attach` | 恢复当前实例内所有可恢复的 detached Feishu 推送 | 变更 | 飞书 `/attach service`，以及 reset 结果卡里的“附着当前实例” |

### 4.3 `binding`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] binding list` | 列出当前实例可见 binding | 只读 | 无 |
| `feishu-codexctl [--instance <name>] binding status <binding_id>` | 查看单个 binding 的 chat、thread、推送状态、next prompt、interaction owner、会话设置 | 只读 | 飞书 `/status`、`/preflight` 的底层诊断面 |
| `feishu-codexctl [--instance <name>] binding attach <binding_id>` | 恢复单个 binding 的飞书推送 | 变更 | 飞书 `/attach binding` |
| `feishu-codexctl [--instance <name>] binding detach <binding_id>` | 暂停单个 binding 的飞书推送，但保留 bookmark | 变更 | 飞书 `/detach` 的 binding 级对应 |
| `feishu-codexctl [--instance <name>] binding clear <binding_id>` | 清除单个 binding bookmark | 变更 | 无 |
| `feishu-codexctl [--instance <name>] binding clear-all` | 清除当前实例下全部 binding bookmark | 变更 | 无 |

`binding clear` / `clear-all` 不是 `detach`：

- `clear` 清的是本地 bookmark
- `detach` 清的是当前飞书推送附着状态

### 4.4 `prompt`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] prompt send --binding-id <binding_id> (--text <text> \| --text-file <file>) [--synthetic-source <label>] [--display-mode silent\|announce]` | 通过目标实例的 control plane，向某个 binding 合成发起一轮新的 prompt turn | 变更 | 无；这是本地 control-plane synthetic prompt 入口 |

说明：

- `prompt send` 是 **binding-scoped**，不是 thread-scoped。
- 真正执行仍会经过当前服务内的 running-turn / attach / interaction 等保护。
- 目标 binding 当前不可写时，命令必须 fail-closed 返回拒绝原因，而不是静默排队。

### 4.5 `thread`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] thread list [--scope cwd\|global] [--cwd <path>]` | 浏览 persisted thread；默认按当前目录过滤 | 只读 | 飞书 `/threads` 的目标发现面 |
| `feishu-codexctl [--instance <name>] thread status (--thread-id <id> \| --thread-name <name>)` | 查看某个 thread 的 backend 状态、live runtime owner / holders、bound / attached / detached bindings | 只读 | 无一条完全等价命令 |
| `feishu-codexctl [--instance <name>] thread bindings (--thread-id <id> \| --thread-name <name>)` | 查看某个 thread 当前关联的 binding 列表 | 只读 | 无 |
| `feishu-codexctl [--instance <name>] thread archive (--thread-id <id> \| --thread-name <name>)` | 归档目标 thread，并清理当前目标实例里仍指向它的 bindings | 变更 | 飞书 `/archive` 的本地实例级对应 |
| `feishu-codexctl [--instance <name>] thread attach (--thread-id <id> \| --thread-name <name>)` | 恢复某个 thread 当前所有 detached bindings 的飞书推送 | 变更 | 飞书 `/attach thread`，以及 reset 结果卡里的“附着当前线程” |
| `feishu-codexctl [--instance <name>] thread detach (--thread-id <id> \| --thread-name <name>)` | 暂停某个 thread 的飞书推送，同时保留 thread 与 binding 关系 | 变更 | 飞书 thread-scoped 的 detach 管理动作 |

说明：

- 本地 `thread detach` 走的是正在运行的 `feishu-codex` 服务控制面。
- 底层实现仍可能调用上游 `thread/unsubscribe`，但这属于内部协议，不再作为用户命令名。

### 4.6 `image`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] image send --path <file> [--thread-id <id> \| --thread-name <name>]` | 把一张本地图片发送到目标 thread 当前所有 attached 的 Feishu bindings | 变更 | 无；这是本地控制面显式动作 |

## 5. 与飞书命令面的对应关系

| 本地命令 | 飞书侧最接近入口 | 关键差异 |
| --- | --- | --- |
| `service reset-backend` | `/reset-backend` | 都是实例级 backend 管理；一个是 CLI，一个是飞书卡片流 |
| `service attach` | `/attach service` | 都是实例级恢复动作；飞书主入口通常来自 reset 结果卡 |
| `binding status <binding_id>` | `/status`、`/preflight` | 本地输出更底层，带 binding id、reason code、interaction owner |
| `binding attach <binding_id>` | `/attach binding` | 本地可直接按任意 binding id 定位；飞书默认作用于当前 chat |
| `binding detach <binding_id>` | `/detach` | 飞书 `/detach` 只作用于当前 chat；本地可直接按任意 binding id 定位 |
| `prompt send --binding-id <binding_id>` | 无 | 本地可以从 service control plane 合成一条未来或系统触发的 prompt；飞书侧当前没有等价 slash 命令 |
| `thread attach --thread-id/--thread-name` | `/attach thread` | 飞书 thread 级动作只能基于当前 chat 当前 thread；本地可直接按任意目标 thread 定位 |
| `thread detach --thread-id/--thread-name` | 无一条完全等价的飞书命令 | 飞书 `/detach` 是当前 chat binding 级；本地 thread 级动作会批量影响该 thread 当前所有 attached bindings |
| `thread list --scope cwd` | `/threads` | 飞书是聊天入口；本地只是线程发现面 |
| `thread status` | `/status`、`/preflight`、`/attach`/`/detach` 的底层诊断 | 本地是 thread-scoped 调试面 |

## 6. 边界

下列期待当前不成立：

- 不能把 `feishu-codexctl` 理解成飞书 `/threads` 的本地 UI
- 不能期待 `feishu-codexctl` 进入 Codex TUI
- 不能把 `binding clear` 理解成 “停掉当前线程推送”

如果新增、删除、改名任何 `feishu-codexctl` 子命令，或改变参数约束、实例解析规则、与飞书面的对应关系，必须同步更新本文。
