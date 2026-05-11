# `profile` / `memory` 收口实施清单

日期：2026-05-11

## 1. 目标

本清单对应两条已确认问题：

1. `thread-wise memory override` 会错误生成 `profiles.<name>.memories`
2. `profile` / `memory` 需要更清晰的 `thread-owned next-load state` 合同

本轮按 3 个阶段推进：

1. 独立修 correctness bug
2. 把合同升格为正式事实源
3. 按合同收口 provisional / pending-seed 生命周期

## 2. 分阶段范围

### 阶段 1：修 `profile.memories` 真实 bug

范围：

- `bot/thread_memory_mode.py`
- `bot/fcodex_proxy.py`
- `bot/codex_handler.py`
- 相关单测

动作：

- `build_thread_memory_config_override()` 不再生成 `profiles.<name>.memories`
- 所有 resume / replacement / new-thread seed 路径统一只写顶层 `memories`
- 增加回归测试，锁定 override shape

验收：

- 带 `profile_name_hint` 时，生成的 override 仍只包含顶层 `memories`
- 相关 resume / thread/start 测试继续通过

### 阶段 2：升格正式合同

范围：

- `docs/contracts/`

动作：

- 新增正式合同文档，写清：
  - `profile` / `memory` 是 thread-owned next-load state
  - 只有 materialized logical thread 才拥有正式 thread-wise persist state
  - provisional 阶段只允许 pending seed
  - loaded thread 使用 load-time observed snapshot；设置变更默认影响下次 load

验收：

- 后续实现与测试可直接引用该合同，而不是继续依赖 `_work` 提案文档

### 阶段 3：按合同收口实现

范围：

- `bot/codex_handler.py`
- `bot/fcodex_proxy.py`
- `bot/runtime_admin_controller.py`
- 必要的共享小模块
- 相关单测

动作：

- 本地 control-plane：
  - 对 provisional target 的 `thread/memory` 改为 fail-close
  - 不再出现 reset 后继续写旧壳 thread id
- `fcodex`：
  - new-thread initial seed 先进入 pending
  - 只在首个成功 `turn/completed` 后 promote 到正式 thread-wise store
  - `thread/resume` 期间可继续读取 pending seed
- 飞书侧：
  - `/new` 默认 memory seed 不再在 create-thread 后立刻写正式 store
  - provisional replacement 不再把 profile / memory 直接写到新壳的正式 store
  - pending seed 在首个成功 turn 后 promote

验收：

- `/new` 后不发首轮 turn，不留下正式 thread-wise `memory` / `profile` 记录
- 首轮 turn 完成后，pending seed 正式 promote
- provisional replacement 后，新壳上能看到有效 next-load 设置，但正式 store 直到 materialize 才写入
- 本地 `thread/memory --reset-backend` 对 provisional target 明确拒绝

## 3. 回归测试清单

- `tests/test_thread_memory_mode.py`
- `tests/test_codex_app_server.py`
- `tests/test_codex_handler.py`
- `tests/test_runtime_admin_controller.py`

## 4. 非目标

本轮不做：

- 新的持久化 pending-seed store
- 跨进程 / 跨服务重启的 provisional seed durability 承诺
- 新增本地 `thread/profile` 控制面

本轮先把合同、主路径和 fail-close 行为收紧。
