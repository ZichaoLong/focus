# `focusctl` 命令矩阵

英文原文：`docs/contracts/focusctl-command-matrix.md`

本文定义本地 `focusctl` 管理面的正式命令面。

它只回答：

- `focusctl` 管哪些资源
- 哪些命令只读，哪些命令改状态
- 线程目标如何选择
- 它和飞书命令面如何对应

## 1. 总原则

- `focusctl` 是 FOCUS 本地管理面，不是第二个 Codex 前端。
- 想继续 live thread，用 `focus` 或 `fcodex`。
- 想装服务、修服务、管理实例、看 binding / thread / service 当前状态，或做本地 thread-scoped 管理，都用 `focusctl`。

## 2. 实例与目标选择

- 除 `instance ...` 这类全局实例目录命令外，其余实例相关命令都可加 `--instance <name>`。
- 显式 `--instance` 始终优先。
- 这里使用的命名实例必须已经先通过 `focusctl instance create <name>` 创建；`focusctl` 不会隐式创建它。
- 省略时按 `preferred-running -> unique-running -> default-running -> current-instance-paths` 规则解析。
- `thread status`、`thread bindings`、`thread goal`、`thread attach`、`thread detach` 必须二选一：
  - `--thread-id <id>`
  - `--thread-name <name>`
- `thread clear-archived-bindings` 必须且只能提供 `--thread-id <id>` 或 `--all`；它不接受 `--thread-name`，避免为了删除本地 binding 再依赖上游 thread name 解析。
  - `--thread-id` 只按给定 thread id 删除指向它的本地 binding，不验证上游 archived 状态。
  - `--all` 会先通过一个运行中的实例查询上游 archived thread 列表，再删除命中的本地 binding；没有可用运行实例时 fail-closed，不修改本地数据。
- `thread archive` 支持两种目标形式：
  - 单线程：`--thread-name <name>` 或 `--thread-id <id>`
  - 批量：重复提供 `--thread-id <id>`；每个目标 thread 都独立按现有单线程 archive 语义路由、归档并清理本地 bindings

## 3. 资源层

`focusctl` 分这些资源：

- `config`
- `instance`
- `service`
- `binding`
- `prompt`
- `thread`
- `image`
- `skill`
- `uninstall`
- `purge`

其中：

- `binding` 是 chat-scoped 视角
- `thread` 是 thread-scoped 视角

两者不要混读。

## 4. 命令表

### 4.1 `instance`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl instance create <name>` | 创建命名实例并准备配置、数据目录与 service 定义 | 变更 | 无 |
| `focusctl instance list` | 列出本机已知实例及其目录；这是已知实例视图，不是运行中实例视图 | 只读 | 无 |
| `focusctl instance remove <name>` | 删除命名实例及其实例级 service 注册材料；不能删除 `default` | 变更 | 无 |

### 4.2 `service`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl [--instance <name>] service start` | 启动目标实例后台 service | 变更 | 无 |
| `focusctl [--instance <name>] service stop` | 停止目标实例后台 service | 变更 | 无 |
| `focusctl [--instance <name>] service restart` | 重启目标实例后台 service | 变更 | 无 |
| `focusctl [--instance <name>] service status` | 查看目标实例 service / control plane / app-server 概况 | 只读 | 无一条完全等价命令 |
| `focusctl service list` | 列出本机当前运行中的实例、owner pid、control endpoint、app-server 地址 | 只读 | 无 |
| `focusctl [--instance <name>] service autostart enable\|disable\|status` | 管理目标实例登录后自动启动 | 变更 / 只读 | 无 |
| `focusctl [--instance <name>] service log [--lines <n>]` | 查看目标实例日志并持续跟随 | 只读 | 无 |
| `focusctl [--instance <name>] service reset-backend [--force]` | 为恢复而重置当前实例 backend，但不重启 FOCUS service | 变更 | 飞书 `/reset-backend` |
| `focusctl [--instance <name>] service attach` | 恢复当前实例内所有可恢复的 detached Feishu 推送 | 变更 | 飞书 `/attach service`，以及 reset 结果卡里的“附着当前实例” |

### 4.3 `binding`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl [--instance <name>] binding list` | 列出当前实例可见 binding | 只读 | 无 |
| `focusctl [--instance <name>] binding status <binding_id>` | 查看单个 binding 的 chat、thread、推送状态、next prompt、当前实例 interaction owner、会话设置 | 只读 | 飞书 `/status`、`/preflight` 的底层诊断面 |
| `focusctl [--instance <name>] binding attach <binding_id>` | 恢复单个 binding 的飞书推送 | 变更 | 飞书 `/attach binding` |
| `focusctl [--instance <name>] binding detach <binding_id>` | 暂停单个 binding 的飞书推送，但保留 binding 记录 | 变更 | 飞书 `/detach` 的 binding 级对应 |
| `focusctl [--instance <name>] binding clear <binding_id>` | 删除单个本地 binding 记录 | 变更 | 无 |
| `focusctl [--instance <name>] binding clear-all` | 删除当前实例下全部本地 binding 记录 | 变更 | 无 |
| `focusctl [--instance <name>] binding clear-stale [--dry-run]` | 删除指向已不可验证为可恢复 thread 的 stale binding 记录；默认扫描所有运行中实例和已知非运行实例，显式 `--instance` 时只作用于该实例 | 变更 | 无；这是本地 binding 记录修复 / 运维入口 |

`binding clear` / `clear-all` / `clear-stale` 不是 `detach`：

- `clear` 删除的是本地 binding 记录，包括其中保存的 thread 指向和 binding-local 设置
- `detach` 清的是当前飞书推送附着状态

`binding clear-stale` 是保留逻辑，事实源是 cleanup 专用的 thread 可操作性检查，而不是普通状态展示：

- 它先通过运行中的 app-server 对 binding 指向的 `current_thread_id` 做 metadata-only `thread/read` presence check，不加载完整 turns/history。
- metadata-only `thread/read` 成功的 thread 视为保留对象；即使普通状态是 `notLoaded`，只要可读出 thread metadata，也不是 stale。
- 明确不可读、未加载且无持久 metadata、或只剩不可恢复 metadata 的 thread 视为 stale，删除对应本地 binding 记录。
- 查询失败、超时、协议错误或无法判断时 fail-closed：保留 binding 并在输出中列为 unknown。
- 运行中实例通过各自 service control plane 清理；已知但未运行的实例直接通过本项目的 binding store API 清理。
- archived thread 的精准清理由 `thread clear-archived-bindings` 负责；`binding clear-stale` 不把 unstable 路径字符串当作 archived 事实源。

### 4.4 `prompt`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl [--instance <name>] prompt send --binding-id <binding_id> (--text <text> \| --text-file <file>) [--synthetic-source <label>] [--display-mode silent\|announce]` | 通过目标实例的 control plane，向某个 binding 合成发起一轮新的 prompt turn | 变更 | 无；这是本地 control-plane synthetic prompt 入口 |

说明：

- `prompt send` 是 **binding-scoped**，不是 thread-scoped。
- 真正执行仍会经过当前服务内的 running-turn / attach / interaction 等保护。
- 目标 binding 当前不可写时，命令必须 fail-closed 返回拒绝原因，而不是静默排队。

### 4.5 `thread`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl [--instance <name>] thread list [--scope cwd\|global] [--cwd <path>]` | 浏览 persisted thread；默认按当前目录过滤 | 只读 | 飞书 `/threads` 的目标发现面 |
| `focusctl [--instance <name>] thread status (--thread-id <id> \| --thread-name <name>)` | 查看某个 thread 的 backend 状态、live runtime owner / holders、bound / attached / detached bindings | 只读 | 无一条完全等价命令 |
| `focusctl [--instance <name>] thread bindings (--thread-id <id> \| --thread-name <name>)` | 查看某个 thread 当前关联的 binding 列表 | 只读 | 无 |
| `focusctl [--instance <name>] thread goal (--thread-id <id> \| --thread-name <name>)` | 查看某个 thread 当前 goal；这是默认 show 形态 | 只读 | 飞书 `/goal` |
| `focusctl [--instance <name>] thread goal set (--thread-id <id> \| --thread-name <name>) [--objective <text>] [--status active\|paused]` | 对某个 thread goal 执行原始 persisted 状态改写，供调试或运维使用；至少提供 `--objective` 或 `--status` 之一 | 变更 | 写 objective 时最接近飞书 `/goal set <objective>`；原始 `--status active\|paused` 改写没有精确飞书等价物 |
| `focusctl [--instance <name>] thread goal clear (--thread-id <id> \| --thread-name <name>)` | 清除某个 thread 当前 goal | 变更 | 飞书 `/goal clear` |
| `focusctl [--instance <name>] thread archive (--thread-id <id> [--thread-id <id> ...] \| --thread-name <name>)` | 归档一个或多个目标 thread；归档成功后清理当前目标实例、其他可达运行实例，以及已知非运行实例里仍指向它的本地 bindings | 变更 | 飞书 `/archive` 的本地运维对应；批量和跨实例本地 binding 清理能力仅本地 CLI 提供 |
| `focusctl [--instance <name>] thread clear-archived-bindings (--thread-id <id> \| --all) [--dry-run]` | 删除已归档 thread 残留的本地 binding 记录；不调用上游 archive；`--thread-id` 删除指向指定 thread 的 binding，`--all` 先查询上游 archived 列表再删除命中的 binding；默认扫描所有运行中实例和已知非运行实例，显式 `--instance` 时只作用于该实例 | 变更 | 无；这是本地 binding 记录修复 / 运维入口 |
| `focusctl [--instance <name>] thread attach (--thread-id <id> \| --thread-name <name>)` | 恢复某个 thread 当前所有 detached bindings 的飞书推送 | 变更 | 飞书 `/attach thread`，以及 reset 结果卡里的“附着当前线程” |
| `focusctl [--instance <name>] thread detach (--thread-id <id> \| --thread-name <name>)` | 暂停某个 thread 的飞书推送，同时保留 thread 与 binding 关系 | 变更 | 飞书 thread-scoped 的 detach 管理动作 |

说明：

- 本地 `thread detach` 走的是正在运行的 FOCUS 服务控制面。
- 底层实现仍可能调用上游 `thread/unsubscribe`，但这属于内部协议，不再作为用户命令名。
- 本地 `thread archive` 的上游 Codex archive 只执行一次；archive 成功后，binding 清理分两层：
  - 运行中的其他实例走各自 service control plane，只清理本地 binding，不再次调用上游 archive。
  - 已知但未运行的实例直接通过本项目的 binding store API 删除同 `thread_id` 的 binding 记录；不直接手写 `chat_bindings.json`。
- 如果某个运行实例的本地清理因 running turn、pending request 或 control plane 不可达而失败，archive 已完成但命令返回非零，并在输出里列出 cleanup warning。
- `thread clear-archived-bindings` 复用同一套本地 binding 清理逻辑，但不执行 archive。它用于补救旧版本残留、外部归档后的残留，或服务重启后无 live owner 时归档路由到其它实例造成的残留。
  - `--thread-id` 是显式修复入口；命令不会为了确认 archived 状态再查询上游。
  - `--all` 是 archived-aware sweep：先通过运行中的 app-server 调用上游 `thread/list archived=true` 收集 archived thread id，然后逐个复用本地清理逻辑。省略 `--instance` 时优先用运行中的 `default` 实例查询，若没有则按实例名选一个运行实例查询，并清理所有可见实例；显式 `--instance` 时该实例必须正在运行，且只清理该实例。

### 4.6 `image`

| 命令 | 作用 | 类型 | 飞书对应 |
| --- | --- | --- | --- |
| `focusctl [--instance <name>] image send --path <file> [--thread-id <id> \| --thread-name <name>]` | 把一张本地图片发送到目标 thread 当前所有 attached 的 Feishu bindings | 变更 | 无；这是本地控制面显式动作 |

## 5. 与飞书命令面的对应关系

| 本地命令 | 飞书侧最接近入口 | 关键差异 |
| --- | --- | --- |
| `service reset-backend` | `/reset-backend` | 都是实例级 backend 管理；一个是 CLI，一个是飞书卡片流 |
| `service attach` | `/attach service` | 都是实例级恢复动作；飞书主入口通常来自 reset 结果卡 |
| `binding status <binding_id>` | `/status`、`/preflight` | 本地输出更底层，带 binding id、reason code、当前实例 interaction owner |
| `binding attach <binding_id>` | `/attach binding` | 本地可直接按任意 binding id 定位；飞书默认作用于当前 chat |
| `binding detach <binding_id>` | `/detach` | 飞书 `/detach` 只作用于当前 chat；本地可直接按任意 binding id 定位 |
| `prompt send --binding-id <binding_id>` | 无 | 本地可以从 service control plane 合成一条未来或系统触发的 prompt；飞书侧当前没有等价 slash 命令 |
| `thread attach --thread-id/--thread-name` | `/attach thread` | 飞书 thread 级动作只能基于当前 chat 当前 thread；本地可直接按任意目标 thread 定位 |
| `thread detach --thread-id/--thread-name` | 无一条完全等价的飞书命令 | 飞书 `/detach` 是当前 chat binding 级；本地 thread 级动作会批量影响该 thread 当前所有 attached bindings |
| `thread goal --thread-id/--thread-name` | `/goal` | 飞书只作用于当前 chat 当前 thread；本地 CLI 是 thread-scoped 调试 / 运维面，可直接读取任意目标 thread 的 goal |
| `thread goal set/clear` | `/goal set`、`/goal clear` | 飞书命令面只覆盖当前 chat 当前 thread；本地 CLI 可以直接定位任意显式目标 thread。`thread goal set --status active\|paused` 只是 thread-scoped persisted goal 改写，不等价于飞书 `/goal pause` / `/goal resume` |
| `thread list --scope cwd` | `/threads` | 飞书是聊天入口；本地只是线程发现面 |
| `thread status` | `/status`、`/preflight`、`/attach`/`/detach` 的底层诊断 | 本地是 thread-scoped 调试面 |

## 6. 边界

下列期待当前不成立：

- 不能把 `focusctl` 理解成飞书 `/threads` 的本地 UI
- 不能期待 `focusctl` 进入 Codex TUI
- 不能把 `binding clear` 理解成 “停掉当前线程推送”
- 不能把 `thread goal set --status active|paused` 理解成 runtime 恢复 / 暂停命令；它不承诺 load、settings sync 或立即执行

如果新增、删除、改名任何 `focusctl` 子命令，或改变参数约束、实例解析规则、与飞书面的对应关系，必须同步更新本文。
