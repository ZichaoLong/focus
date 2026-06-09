# 定时续跑与 Synthetic Prompt 合同

英文原文：`docs/contracts/scheduled-prompts.md`

本文定义当前仓库针对“未来某个时间点继续同一 Feishu 绑定 thread”的正式最小合同。

它覆盖三层：

- service control plane：`binding/submit-prompt`
- 本地 CLI：`feishu-codexctl prompt send`
- Linux `systemd --user` managed skill：`feishu-scheduled-prompts`

## 1. 目标

当前正式支持的不是“内建 scheduler 子系统”，而是：

- 在未来时点，安全地向某个既有 Feishu binding 合成发起一轮新的 prompt
- 继续复用同一个 `feishu-codex` 实例 backend
- 保持现有 running-turn / attach / interaction / live-runtime 安全边界

当前明确不支持：

- 持久化 scheduler / job queue
- 跨 binding fan-out prompt
- 另起一个裸 Codex backend 去恢复同一 thread

## 2. `binding/submit-prompt`

control plane 新增：

- `binding/submit-prompt`

它的合同是：

- 作用域是 **binding**，不是 thread
- 入参至少要有：
  - `binding_id`
  - `text` 或 `input_items`
- 可选：
  - `actor_open_id`
  - `synthetic_source`
  - `display_mode`
- 目标 binding 必须已经存在；缺失 binding 时必须 fail-close，不能隐式创建新 binding
- 允许目标 binding 当前尚未绑定 thread；这里指的是“已有 binding，但当前无 thread”，此时沿用普通 prompt 入口的“先建 thread 再启动 turn”语义
- 允许目标 binding 当前是 `detached`；若 attach / resume 预检可通过，则按现有绑定恢复路径执行
- 所有真正写入前的检查都必须复用现有安全边界，而不是旁路

返回值合同：

- `started=true`
  - 表示 turn 已成功发起
- `queued=true`
  - 表示目标 binding 正在执行，且该 synthetic prompt 已进入同一 binding 的本地 FIFO
  - 返回值应包含 `queue_position`
  - 出队时必须重新读取该 binding 的最新 next-turn 设置，如 `/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode`
- `started=false`
  - 表示 fail-closed 拒绝或启动失败
  - 必须返回 `reason`；若有明确 reason code，也应返回 `reason_code`

## 3. `feishu-codexctl prompt send`

本地 CLI 新增：

- `feishu-codexctl [--instance <name>] prompt send --binding-id <binding_id> (--text <text> | --text-file <file>)`

它的合同是：

- 这是 `binding/submit-prompt` 的正式本地入口
- 默认是 `display_mode=silent`
- 可额外传：
  - `--synthetic-source`
  - `--display-mode silent|announce`
  - `--actor-open-id`
- 目标 binding 当前不可写时：
  - 退出码必须非零
  - 输出必须带拒绝原因
- 如果目标 binding 只是“自己的当前 turn 正在执行”，则不视为不可写；该 prompt 进入同一 binding 的本地 FIFO，并由当前实例在 active execution 结束后继续执行

## 4. `display_mode`

当前只支持两个模式：

- `silent`
  - 不额外发“这是系统触发”的说明消息
  - 若成功，正常执行卡 / 终态卡仍按现有运行时逻辑产生
- `announce`
  - 先向目标 chat 发送一条简短触发说明，再启动 synthetic prompt

当前没有更复杂的消息编排合同。

## 5. `feishu-scheduled-prompts` skill

当前正式提供一个 Linux-only managed skill：

- `feishu-scheduled-prompts`

它的合同是：

- 目标是管理 `systemd --user` timer/service
- 到点后仍然通过 `feishu-codexctl prompt send` 回到当前实例 control plane
- 不直接调用独立 Codex SDK helper
- 不直接依赖飞书消息回环

skill helper 当前提供：

- `create`
- `list`
- `show`
- `remove`
- `run-now`

这些 helper 不是飞书 slash 命令，也不是正式的跨平台公共产品面；它们只是 Linux 本机短期方案。

## 6. 安全边界

以下约束是正式合同：

1. 定时任务只是“未来时点发起一次新的 prompt”。
2. 定时任务不能绕过当前实例的 interaction / attach / running-turn 保护。
3. 只有目标 binding 自己的 running-turn 冲突可以进入本地内存 FIFO；跨 binding、interaction owner 冲突、attach/preflight 失败仍必须 fail-closed。
4. 当前不做跨实例自动抢占 live runtime owner。
5. Linux skill 只是调度壳；真正执行面仍是 `binding/submit-prompt`。

## 6.1 Binding FIFO

Feishu 普通 prompt、`feishu-codexctl prompt send` / `binding/submit-prompt`、以及 `/compact` 共享同一个 binding admission 语义：

- 当前 binding idle 时，立即执行
- 当前 binding 有 active execution 时，只有同一个 binding 可入队；队列准入不再额外要求 `actor_open_id` 与当前 running turn 的 actor 相同
- `actor_open_id` 仍是身份、审计、运行时交互归属与回复上下文的一部分，但不是同 binding 排队的额外分区键
- 队列只保存在当前进程内存中，不承诺服务重启恢复、列表、取消或跨 binding 排队
- `/compact` 入队后出队时会先建立本地 execution anchor，再调用上游 `thread/compact/start`，避免 compact 后的 prompt 穿透
- `/model`、`/effort`、`/approval`、`/permissions`、`/collab-mode` 等设置命令不入队，立即修改 binding-wise next-turn 设置；后续出队 prompt 读取最新设置

## 7. 平台边界

当前仓库只把 `systemd --user` 方案作为正式短期实现。

因此：

- `feishu-scheduled-prompts` helper 当前只承诺 Linux
- macOS / Windows 当前没有对应的受管定时 helper 合同

如果后续新增跨平台 scheduler 产品面，本文必须同步更新。
