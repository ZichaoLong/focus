# round6 follow-up 执行清单 - 2026-05-08

> 本文不是新的正式合同；它只把两份 round6 审视报告与本轮人工复核后的判断，收敛成一份可执行清单。
>
> 输入来源：
>
> - `docs/_work/codebase-audit-2026-05-08-round6.zh-CN.md`
> - `docs/_work/codebase-audit-2026-05-08-round6-claude.zh-CN.md`
> - 本轮对相关代码路径与本地故障现象的复核

## 1. 结论摘要

- 应优先处理的不是“文案统一”，而是两处 runtime 单一事实源破坏：
  1. websocket 断开后可能留下假 `attached`
  2. `archive` 路径可能漏掉 backend `thread/unsubscribe`
- 当前还存在一条必须尽快消掉的验证红线：
  - `CodexHelpDomain` 构造签名已变，但共享命令面测试未同步
- `CodexThreadsUiDomain` 的宽 owner protocol 仍是明确架构债，但优先级低于上面三项真实行为问题。
- Claude 那份报告里的 CLI / 文档双 SOT 问题基本成立，但属于收尾清理，不应先于 runtime 真 bug。
- 明确不做：**不为旧持久化状态值增加长期兼容 repair / 自动迁移路径。**

## 2. 明确保留的工程立场

### 2.1 不做持久化兼容 repair 路径

本轮已遇到一次本地数据故障：

- `chat_bindings.json` 中仍残留旧值 `feishu_runtime_state: released`
- 当前代码只接受 `attached` / `detached`
- 结果是服务启动时 fail-close 拒绝继续运行

对此的结论是：

- 不在产品代码里增加长期保留的“旧状态自动修复 / 自动迁移”逻辑
- 不在 install / bootstrap 热路径里增加兼容分支
- 当前 schema 就是唯一合法 schema

允许的运维方式只有两类：

- 手动修本地数据
- 或直接清空 data dir

### 2.2 失败方式必须可操作

既然选择 fail-close，就必须保证错误足够可操作。后续若继续收紧这块，报错至少应包含：

- 哪个持久化文件非法
- 哪个字段非法
- 当前读到了什么值
- 当前允许值是什么

但这里的补强应停留在“报错更清楚”，**不应**演化成“自动兼容旧几代状态”的常驻机制。

## 3. 执行优先级

### P0：修 websocket 断开后的假 `attached`

采纳。应作为最高优先级 runtime 修复项。

问题判断：

- 当前 `attached` 被用户理解为“当前飞书会话仍会收到该 thread 的推送”
- 但 websocket 断开时，`bot/codex_protocol/client.py` 只会结束 reader loop 并清空 `_ws`
- 本地 binding runtime snapshot 不会自动降级
- `bot/runtime_admin_controller.py` 里的 `attach_binding()` 又会在本地已是 `attached` 时短路返回

这会导致：

- 用户面显示 `attached`
- 实际 backend subscription 已消失
- 后续 `/attach` 还可能因为本地快照是 `attached` 而不重新建立真实订阅

执行要求：

- 明确定义：`attached` 只能表示“当前服务连接已建立真实 backend subscription”
- websocket 断开后，应把受影响的 Feishu runtime fail-close 成 `detached`
- 不引入额外的隐藏第四状态来维持“看起来 attached、实际未验证订阅”的中间态

完成标准：

- 断线后，飞书侧不会继续显示假 `attached`
- 后续 `/attach` 或下一次正常 attach 操作，能够重新触发真实 `thread/resume` / subscription 建立
- 测试覆盖 websocket 断开后的状态收敛

### P0：修 `archive` 路径漏掉 backend `thread/unsubscribe`

采纳。与上一项同级。

问题判断：

- 当前正常 detach / deactivate 路径会同时处理：
  - binding runtime
  - backend unsubscribe
  - service runtime lease release
- 但 `archive` 走的是一条近似、却不完整的旁路清理流程

这会导致幽灵状态：

- binding 已清
- lease 已放
- backend 仍可能继续订阅该 thread

执行要求：

- `archive` 不再手写一套近似清理逻辑
- 必须收敛到和普通 deactivate / detach 一样的完整 helper 或统一出口
- 至少要明确处理：
  - 收集 `unsubscribe_thread_id`
  - 去重
  - backend `thread/unsubscribe`
  - release service runtime lease

完成标准：

- `archive` 后不会残留“无 binding / 无 lease / 仍订阅”的状态
- 测试必须显式断言 backend unsubscribe 已发生
- 测试还应覆盖“只有最后一个 service-side subscriber 消失时才真正 unsubscribe”

### P1：修测试基线不绿

采纳。应在上面两项 runtime 修复并行或紧随其后处理。

问题判断：

- `tests/test_shared_command_surface.py` 仍按旧签名构造 `CodexHelpDomain`
- 当前实现已经要求显式注入 `get_runtime_state`

这类问题的性质不是“测试待补”，而是：

- main 基线不绿
- 会把后续真实回归淹没在已知噪声里

执行要求：

- 把共享命令面测试与当前 `CodexHelpDomain` 合同对齐
- 恢复“全量测试应当可作为可信基线”的状态

### P2：继续收 `CodexThreadsUiDomain` 的 ports 边界

采纳，但排在 runtime 真 bug 和测试基线之后。

问题判断：

- 当前 `CodexThreadsUiDomain` 虽已有 `ThreadsUiRuntimePorts`
- 但仍大量依赖 handler 私有 owner：
  - `bot`
  - `_adapter`
  - `_lock`
  - `_reply_text`
  - `_resolve_resume_target`
  - `_read_thread_summary_authoritatively`
  - `_archive_thread_for_control`

这与 architecture 文档已经写明的方向不一致：

- bot-facing domain 应通过具名 ports 获取必要能力
- 不应继续依赖带 `bot: Any` 的宽 owner protocol

执行要求：

- 继续拆 ports，而不是继续向 owner protocol 塞新能力
- 至少把下列职责从宽 owner 上剥离出来：
  - thread read / resolve
  - thread mutate（rename / archive）
  - card patch / reply
  - runtime view

完成标准：

- `CodexThreadsUiDomain` 不再直接摸 `_adapter`、`bot`、handler 私有 `_xxx` helper
- 依赖面按职责分组，而不是继续累积隐式 owner surface

### P3：文档与 CLI 的双 SOT 清理

采纳，但属于收尾项，不应抢在前面。

#### 3.1 `/detach` 曝光页描述漂移

采纳。

当前实现与 help 合同都已经把 attach / detach toggle 放到“当前会话”页；`feishu-command-matrix` 仍有旧描述写成“当前线程”页。这是直接合同漂移，应机械化修正。

#### 3.2 `focusctl` `_live_runtime_summary` legacy fallback

基本采纳，倾向删除。

如果 service 已稳定返回：

- `live_runtime_owner`
- `live_runtime_holder_labels`

那么 CLI 不应再在本地重拼一遍 holder label。按仓库当前工程立场，宁可 fail-close，也不保留无必要 fallback。

#### 3.3 `verifiably globally unloaded` 的规则源收敛

采纳，但仅做轻量收敛。

建议把 `docs/contracts/thread-profile-semantics.zh-CN.md` 作为这一规则的单一事实源；其他文档保留摘要与链接，不再各自重复完整定义。

#### 3.4 `runtime-control-surface` 重列 `focusctl` 命令名

采纳，但优先级最低。

若 `focusctl-command-matrix` 已是正式命令矩阵，则 `runtime-control-surface` 应只保留指针，不再维护第二份命令清单。

## 4. 推荐执行顺序

1. 先修 websocket 断线后的假 `attached`
2. 再修 `archive` 漏 `thread/unsubscribe`
3. 立即补齐测试，使基线恢复可验证
4. 再收 `CodexThreadsUiDomain` 的 ports 边界
5. 最后清理文档漂移与 CLI / 文档双 SOT

## 5. 明确不纳入本轮的事项

下列项不应混进本轮执行清单：

- 为旧持久化状态值增加 install-time repair
- 为旧持久化状态值增加 service 启动时自动迁移
- 为兼容历史命名继续保留 `released` 一类长期 alias
- 先做文档润色，再回头补 runtime 真 bug

如果未来再次出现旧数据不兼容：

- 默认仍按 fail-close 处理
- 优先修报错可操作性
- 不默认引入新的兼容迁移代码
