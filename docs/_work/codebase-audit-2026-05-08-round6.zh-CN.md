# codebase audit - 2026-05-08 round 6

## 范围与基线

- 审视对象：`main` 当前 HEAD `05fd301` (`Unify runtime attach and detach control surface`)
- 审视目标：
  - 单一事实源是否仍被破坏
  - runtime / binding / attach-detach / backend 语义是否仍有分叉
  - 当前架构边界是否和正式文档一致
  - 测试与代码是否仍保持同步
- 审视原则：遵从 `AGENTS.md`
  - clear architecture
  - easy maintenance
  - unambiguous behavior
  - fail-closed over ambiguous best-effort behavior

## 结论摘要

- 本轮提交完成了 `attach / detach` 用户面与大部分内部命名收敛，也补了一个真实 bug：
  - `/attach` 不再对已 loaded thread 走只读 `thread/read` 假附着路径，而是改为通过 `thread/resume` 建立真实 backend subscription
- 但当前 HEAD 仍有两处高优先级状态分叉问题：
  1. websocket 断开后，binding 仍可能停留在假 `attached`
  2. `archive` 路径可能清 binding、放 lease，但没有对 backend 发 `thread/unsubscribe`
- 另外还有一处明确的代码/测试漂移：
  - 全量 `unittest` 不绿，`CodexHelpDomain` 构造签名变更后测试未同步
- 以及一处仍应继续收紧的架构债：
  - `CodexThreadsUiDomain` 仍大量依赖 handler 私有 owner surface，与当前 architecture 文档的 ports 化方向不一致

## Findings

### 1. 高：websocket 断开后仍可能留下假 `attached`，破坏“飞书会话是否接收推送”的单一事实源

#### 现象

当前 `attached` 仍不是 backend 订阅事实的完全可靠投影。

如果服务 websocket 断开：

- backend connection 上的真实 thread subscription 已消失
- 但本地 binding runtime snapshot 不会自动降级成 `detached`
- 后续 `/attach` 还可能因为“本地已 attached”被短路成 no-op

于是用户会看到：

- 状态上仍是 `attached`
- 但飞书再也收不到本地 `fcodex` 或其他订阅者驱动的推送

#### 证据

- [bot/codex_protocol/client.py](../../../bot/codex_protocol/client.py)
  - `CodexRpcClient._reader_loop()` 在连接断开时只会：
    - `_fail_pending(...)`
    - `self._ws = None`
  - 它不会通知上层把相关 thread/binding fail-close 成 `detached`
- [bot/runtime_admin_controller.py](../../../bot/runtime_admin_controller.py)
  - `attach_binding()` 在本地 snapshot 已是 `FEISHU_RUNTIME_ATTACHED` 时直接返回 `already_attached`
  - 这意味着“本地状态已 attached”会屏蔽一次真正的重附着动作
- [bot/codex_handler.py](../../../bot/codex_handler.py)
  - `_restore_service_thread_runtime_leases()` 只在 `on_register()` 运行
  - 当前没有“连接断开后重连，再重新建立 service connection thread subscription”的收口

#### 为什么这是单一事实源问题

正式合同已经把“飞书是否接收推送”收敛为 `attach / detach` 这一层。

如果 `attached` 只表示“本地历史上曾经附着过”，而不是“当前服务连接真的还在订阅 backend thread”，那么：

- `attached` 就不再是事实，而只是缓存
- 用户面、控制面、内部状态机会再次分叉

#### 建议

- 定义清楚：`attached` 必须表示“当前服务连接已建立真实 backend subscription”
- 一旦 app-server websocket 断开：
  - 要么把所有当前 `attached` binding fail-close 成 `detached`
  - 要么引入一层显式 `subscription_verified` / `connection_attached` 状态，禁止把它继续投影成用户面 `attached`
- 更推荐前者：
  - 语义更简单
  - fail-closed
  - 不再引入第四层隐藏状态

### 2. 高：`archive` 路径可能漏掉 backend `thread/unsubscribe`，形成“无 binding / 无 lease / 仍订阅”的幽灵状态

#### 现象

`archive_thread_for_control()` 当前会：

- archive thread
- 遍历当前实例里所有 bound bindings
- 调用 `_deactivate_binding_locked(binding)`
- 最后 `_release_service_thread_runtime_lease(thread_id)`

但它丢弃了 `_deactivate_binding_locked()` 的返回值 `unsubscribe_thread_id`。

这意味着它可能：

- 已把 binding 清掉
- 已把 service runtime lease 放掉
- 却没有让 backend 真正执行 `thread/unsubscribe`

#### 证据

- [bot/runtime_admin_controller.py](../../../bot/runtime_admin_controller.py)
  - `archive_thread_for_control()` 的清理循环里，`self._deactivate_binding_locked(binding)` 只被调用，没有消费返回值
  - 紧接着直接 `_release_service_thread_runtime_lease(normalized_thread_id)`
- [bot/codex_handler.py](../../../bot/codex_handler.py)
  - 对比正常清理路径：
    - `deactivate_sender()`
    - `handle_chat_unavailable()`
  - 都会在拿到 `unsubscribe_thread_id` 后显式：
    - `self._adapter.unsubscribe_thread(unsubscribe_thread_id)`
    - `self._release_service_thread_runtime_lease(unsubscribe_thread_id)`

#### 为什么这是单一事实源问题

这里把“binding 是否存在”“service 是否持有 runtime lease”“backend connection 是否仍订阅 thread”拆成了三条不同清理路径。

正常路径会同时更新三层事实；archive 路径只更新了两层。

这是典型的旁路写：

- 不是通过一个统一的“binding deactivation + backend unsubscribe + lease release”收口完成
- 而是在 archive 里手写了一套近似但不完整的清理流程

#### 测试缺口

当前测试没有兜住这个 bug，反而掩盖了它。

- [tests/test_runtime_admin_controller.py](../../../tests/test_runtime_admin_controller.py)
  - `RuntimeAdminController` 测试注入的是：
    - `deactivate_binding_locked=lambda binding: binding_runtime.deactivate_binding_locked(binding)`
  - 也就是说，测试替身本身就不负责 `unsubscribe_thread`
  - 于是 archive 测试只验证：
    - binding 被清
    - lease 被放
  - 没验证 backend `unsubscribe` 是否发生

#### 建议

- 把 archive 的 binding 清理收敛到和普通 clear/deactivate 相同的完整 helper
- 至少要统一成：
  - 收集 `unsubscribe_thread_id`
  - 去重
  - 统一做 backend `thread/unsubscribe`
  - 再 release service runtime lease
- 同时补测试：
  - archive 后应显式看到 `unsubscribe_thread` 被调用
  - 且只在最后一个 service-side subscriber 消失时调用

### 3. 中：全量测试不通过，`CodexHelpDomain` 构造签名已变，但共享命令面测试未同步

#### 现象

当前 HEAD 上跑全量 `unittest discover` 不绿。

失败点是：

- `tests/test_shared_command_surface.py`
  - 两个测试仍按旧签名构造 `CodexHelpDomain(local_thread_safety_rule="测试规则")`
- 但当前实现已经要求显式注入 `get_runtime_state`

#### 证据

- [bot/codex_help_domain.py](../../../bot/codex_help_domain.py)
  - `CodexHelpDomain.__init__(..., get_runtime_state, ...)`
- [tests/test_shared_command_surface.py](../../../tests/test_shared_command_surface.py)
  - 仍按旧方式直接实例化

#### 影响

- 当前工作树不是可验证的绿色基线
- 后续任何人继续做 refactor 时，会被这个噪声掩盖真实回归

#### 建议

- 先把 `test_shared_command_surface` 与当前 `CodexHelpDomain` ports 合同对齐
- 然后恢复“全量 unittest 必须绿”的开发基线

## 架构债

### 4. 中：`CodexThreadsUiDomain` 仍大量依赖 handler 私有 owner，和 architecture 文档的 ports 边界不一致

#### 现象

当前 threads UI domain 虽然已经把“resume 切换”抽成了 `ThreadsUiRuntimePorts`，但整体上仍是半收敛状态。

它仍直接依赖：

- `bot: Any`
- `_adapter`
- `_lock`
- `_get_runtime_view`
- `_resolve_resume_target`
- `_read_thread_summary_authoritatively`
- `_archive_thread_for_control`
- `_reply_text`

并且会直接：

- `self._owner.bot.patch_message(...)`
- `self._owner._adapter.rename_thread(...)`

#### 证据

- [bot/codex_threads_ui_domain.py](../../../bot/codex_threads_ui_domain.py)
  - `_ThreadsUiDomainOwner` 仍是宽 owner protocol
  - `refresh_threads_card_message()` 直接 patch bot message
  - rename/archive/read 等都直接回摸 handler 私有 helper

#### 为什么是架构债

当前正式架构文档已经明确写了：

- session UI 发起的 runtime 流程应通过显式 ports 穿过边界
- bot-facing domain 不应继续保留宽泛 owner protocol

见：

- [docs/architecture/feishu-codex-design.zh-CN.md](../architecture/feishu-codex-design.zh-CN.md)

也就是说，这里不是“文档没想清楚”，而是“文档已收敛，代码还没完全跟上”。

#### 建议

- 把 `CodexThreadsUiDomain` 继续拆成更小的 ports：
  - thread read/resolve
  - thread mutate(rename/archive)
  - card patch / reply
  - runtime view / admin guard
- 最终让它不再知道：
  - `_adapter`
  - `bot`
  - `_lock`
  - handler 私有 `_xxx` helper 名称

## 验证记录

### 已执行

1. 局部测试
   - `~/.local/share/feishu-codex/.venv/bin/python -m unittest tests.test_codex_handler`
   - 通过
2. 全量基线
   - `~/.local/share/feishu-codex/.venv/bin/python -m unittest discover -s tests`
   - 结果：`656` tests, `2` errors
   - 失败点：
     - `test_shared_command_surface.SharedCommandSurfaceTests.test_generated_cards_do_not_emit_plugin_payload_keys`
     - `test_shared_command_surface.SharedCommandSurfaceTests.test_help_thread_and_threads_cards_reuse_shared_command_specs`

### 环境说明

- 项目运行时里当前没有 `pytest` 模块
- 因此本轮只记录 `unittest` 基线
- 上游 `lark_oapi/pkg_resources` deprecation warning 仍存在，但不属于本轮新问题

## 建议优先级

1. 先修 websocket 断开后的假 `attached`
2. 再修 archive 漏 `thread/unsubscribe`
3. 同步 `CodexHelpDomain` 测试，恢复全量绿色基线
4. 最后继续把 `CodexThreadsUiDomain` 从宽 owner protocol 收敛到显式 ports

