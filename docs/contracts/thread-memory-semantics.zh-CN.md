# Thread Memory 语义（已退役）

英文原文：`docs/contracts/thread-memory-semantics.md`

本文保留原文件名，仅作为退役说明。

## 当前状态

本项目已移除 thread-wise memory 控制面。

因此，以下入口都不再属于正式合同：

- `/memory`
- `feishu-codexctl thread memory`
- `new_thread_memory_mode_seed`
- 项目自管的 thread memory 持久化与恢复链路

## 替代方案

如果用户希望改变上游 memory/provider 相关行为，应通过：

- 实例 startup profile
- 上游 `~/.codex/config.toml`
- profile-v2

如果用户希望改变某个飞书会话后续 turn 的运行时行为，应通过：

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

## 相关正式文档

- 当前设置分层：`docs/contracts/runtime-settings-fact-sources.zh-CN.md`
- 当前飞书控制面：`docs/contracts/runtime-control-surface.zh-CN.md`
- 退役后的 next-load 说明：`docs/contracts/thread-next-load-settings-semantics.zh-CN.md`
