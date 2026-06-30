# 同实例 Thread-to-Thread 通信计划 — 2026-05-12

Status: working material under `docs/_work/`. Not a repository fact.

本文记录一套**先收窄、再实现**的 thread-to-thread 通信方案。

当前目标不是做“跨实例分布式线程网络”，而是先定义一条**长期可靠、同实例、thread-first** 的正式演进方向，供后续实现使用。

## 1. 范围

本文只讨论：

- 同一个 `feishu-codex` instance 内的 persisted threads 之间如何通信
- 如何把“消息事实”与“唤醒执行”拆开
- 如何避免继续把 binding 当成线程间通信的主抽象
- 如何提供**本项目自己的命令行入口**，而不是给 Codex 额外注入一个专用工具

本文当前**不**讨论：

- 跨实例通信
- 跨机器通信
- 以 Feishu chat binding 作为通信主键
- 完整的多线程调度编排系统

## 2. 背景与目标

当前需求已经收敛为一种典型工作流：

- 用户正在与某个 thread 交互
- 用户希望该 thread 在工作过程中，把一部分任务交给另一个 thread
- 目标 thread 通常通过**线程名**被提及，例如 `a`、`b`、`c`
- 目标 thread 不一定长期扮演固定角色；它只是另一个可协作的 thread

这里真正需要的不是：

- 让一个 thread 直接“假装发飞书消息”给另一个会话
- 让 prompt body 充当唯一的通信事实
- 让所有线程默认跨实例互通

这里真正需要的是：

1. 一条 durable 的消息事实链路
2. 一条可选的唤醒 / 执行链路
3. 一份同步回执，让发送方立刻知道这次发送发生了什么

## 3. 当前代码与上游的硬事实

### 3.1 当前正式 synthetic prompt 入口仍是 binding-scoped

当前仓库已正式支持：

- `binding/submit-prompt`
- `focusctl prompt send --binding-id ...`

这条链路适合：

- 定时续跑
- 系统将 prompt 回灌到某个既有 Feishu binding

它**不适合**成为 thread-to-thread 通信的一等能力，因为它的主键仍是 binding，不是 thread。

相关参考：

- [docs/contracts/scheduled-prompts.zh-CN.md](../../docs/contracts/scheduled-prompts.zh-CN.md)
- [docs/contracts/focusctl-command-matrix.zh-CN.md](../../docs/contracts/focusctl-command-matrix.zh-CN.md)

### 3.2 上游已具备 thread 级执行原语

上游 `codex app-server` 已提供：

- `thread/start`
- `thread/resume`
- `turn/start`
- `thread/read`
- `thread/loaded/list`

因此，如果只考虑“让某个 persisted thread 在当前实例里跑起来”，上游原语是够的。

其中必须再次强调：

- `thread/read` 只是历史 / 元数据读取
- 它不是 live attach / resume 的替代物

相关参考：

- `codex-rs/docs/codex_mcp_interface.md`
- [docs/contracts/feishu-thread-lifecycle.zh-CN.md](../../docs/contracts/feishu-thread-lifecycle.zh-CN.md)

### 3.3 当前项目已有 thread 安全边界

当前正式合同已经明确：

- live runtime owner / runtime lease 用于限制跨实例 live attach
- interaction owner 用于限制当前谁能写入 / 中断 / 补充输入
- thread-wise next-load state 与 frontend-owned runtime settings 必须分开

因此，线程间通信如果要做成长期可靠的产品面，不能绕开这些现有边界。

相关参考：

- [docs/contracts/runtime-control-surface.zh-CN.md](../../docs/contracts/runtime-control-surface.zh-CN.md)
- [docs/contracts/local-command-and-thread-profile-contract.zh-CN.md](../../docs/contracts/local-command-and-thread-profile-contract.zh-CN.md)

## 4. 设计收敛结论

### 4.1 只做同实例通信

当前正式建议是：

- thread-to-thread 通信只在**同一个运行中的实例**内成立
- 若目标 thread 当前由其他实例持有 live runtime，则直接 fail-close

原因：

- 这能避免跨实例调度、转发、接管带来的安全与一致性问题
- 它与当前项目已经收紧的 live runtime admission 方向一致

### 4.2 thread-first，而不是 binding-first

线程间通信的正式主键应是：

- `thread_id`

用户面可以继续使用：

- `thread_name`

但这只是解析入口，不是底层事实源。

因此：

- binding 可以不存在
- Feishu chat 可以不存在
- `fcodex` TUI 也可以不存在

只要目标 thread 是 persisted thread，且当前实例可安全 resume，它就应当是可通信、可执行的。

### 4.3 “消息事实”与“唤醒执行”必须拆开

这是本文的核心结论。

建议拆成两层：

1. `message delivery`
   - 只负责把消息 durable 地放进目标 thread 的 mailbox
2. `wake / execution`
   - 只负责尝试让目标 thread 在当前实例里真正运行

这样定义后：

- “消息已送达”不再依赖 Feishu binding
- “消息已送达”也不再依赖目标 thread 此刻是否有人盯着
- 唤醒失败时，消息事实仍然成立

### 4.4 “回执”与“回信”必须区分

发送方这边必须立即拿到的是：

- 一份同步回执

而不是：

- 目标 thread 的真正工作结果

因此正式语义应是：

- 发信必须有**回执**
- 发信不要求立刻有**回信**

### 4.5 跨实例占用与同实例忙碌要区别处理

这两种情况不能混。

1. 目标 thread 当前由其他实例持有
   - 这是安全边界问题
   - 建议：`fail-close`
2. 目标 thread 当前在同实例内忙碌
   - 这是正常运行态问题
   - 建议：消息入箱，但延后唤醒

也就是：

- `other instance`：拒绝
- `busy same instance`：接收并排队

### 4.6 主入口应是本项目 CLI，而不是 Codex 注入工具

当前建议的主入口是：

- 本项目自己的 control plane + CLI

而不是：

- 给 Codex 工具集额外注入一个“线程间发消息”专用工具

原因：

- CLI 更符合本项目已有管理面形态
- 可以让 skill、shell、管理员脚本复用同一入口
- 不把 thread-to-thread 通信能力绑死在某个前端的工具注入策略上

后续若要给模型可用：

- 应通过 skill 或 shell 约定去调用该 CLI
- skill 只是包装层，不应成为一等事实源

## 5. 推荐的正式抽象

### 5.1 Mailbox

建议新增：

- thread-scoped mailbox store

它的作用是：

- 记录“谁给谁发了什么”
- 记录是否已经被目标 thread 消费
- 记录每次发送时的 delivery / wake 回执

建议它成为这项能力的**单一事实源**。

### 5.2 Wake

建议新增：

- thread-scoped wake path

它只负责：

- 在当前实例里尝试 resume / start target thread
- 让 target thread 处理 mailbox 中待消费的消息

### 5.3 System / Relay Interaction Holder

当前 `interaction owner` 只有：

- `feishu`
- `fcodex`

如果未来由 service 自己基于 mailbox 主动唤醒某个 target thread，则建议新增第三类：

- `system`
- 或 `relay`

它的职责是：

- 明确“这轮 turn 不是来自 Feishu，也不是来自本地 TUI”
- 避免 thread-scoped synthetic wake 落到模糊所有权路径

## 6. 控制面与 CLI 草案

本文先锁**分层**，命令拼写可以后续微调。

### 6.1 control plane 草案

建议至少新增两层能力：

- `thread/message/send`
- `thread/wake`

其中：

- `thread/message/send`
  - 负责 delivery
  - 可以内部顺带尝试 wake
  - 但语义上不把二者混为一个事实
- `thread/wake`
  - 可以作为独立内部能力
  - 供 delivery 后自动触发，也供后续管理面显式使用

### 6.2 本地 CLI 草案

建议主入口先放在 `focusctl` 下。

可接受的方向例如：

- `focusctl thread send-message ...`
- `focusctl thread inbox ...`

本文当前不锁死子命令拼写，但锁死三点：

1. 这是本项目 CLI，不是 Codex 内建 slash 命令
2. 这是 thread-scoped，不是 binding-scoped
3. 若在 Codex turn 内调用，可优先读取 `CODEX_THREAD_ID` 作为 `from_thread_id`

因此，建议的调用语义是：

- 在 thread 内部调用时：
  - `from_thread_id` 可省略，默认取 `CODEX_THREAD_ID`
- 在管理员 / 脚本场景下：
  - 允许显式传 `--from-thread-id` 或 `--from-thread-name`

## 7. 目标解析与名字语义

### 7.1 对用户保留 thread name

用户仍然可以说：

- 给 `a` 发消息
- 让 `b` review 一下

这符合当前真实使用习惯。

### 7.2 内部必须解析成 thread id

内部执行时必须把目标解析成：

- `target_thread_id`

如果发生以下情况，必须 fail-close：

- 当前实例内没有这个 thread name
- 命中多个同名 thread
- 目标 thread 当前由其他实例持有 live runtime

### 7.3 联系人 / 别名注册表不是 MVP 必需项

当前更推荐的第一版是：

- 直接按真实 `thread_name` 解析
- 要求在同实例范围内唯一

后续若再做增强，可新增：

- sender-thread scoped contacts / alias registry

但这不是第一阶段的必需项。

## 8. 发送回执合同草案

建议每次 `thread/message/send` 都返回结构化回执。

建议字段：

- `ok`
- `message_id`
- `from_thread_id`
- `to_thread_id`
- `delivery_status`
- `wake_status`
- `reason_code`
- `reason`

建议最小状态集合如下。

### 8.1 delivery_status

- `stored`
- `rejected`

### 8.2 wake_status

- `started`
- `pending_target_busy`
- `blocked_other_instance`
- `blocked_pending_input`
- `blocked_not_routable`
- `not_requested`

### 8.3 建议语义

1. 目标线程被其他实例持有
   - `delivery_status=rejected`
   - `wake_status=blocked_other_instance`
2. 目标线程在同实例忙碌
   - `delivery_status=stored`
   - `wake_status=pending_target_busy`
3. 目标线程可立即运行
   - `delivery_status=stored`
   - `wake_status=started`

这份回执是控制面结果，不等于目标 thread 的最终回复。

## 9. “没有 frontend 的目标 thread”应如何处理

这是当前方案优于 binding-scoped 思路的关键点。

若目标 thread：

- 没有 Feishu binding
- 没有 attached chat
- 没有本地 `fcodex`

但它仍然是 persisted thread，并且：

- 当前实例可安全 resume
- 不被其他实例持有

则当前 service 应当仍能：

- 接收消息到 mailbox
- 尝试 `thread/resume`
- 在需要时为它发起一轮 synthetic wake

也就是说：

- “没有 frontend”不应阻止 delivery
- 它至多影响 wake 是否能立刻成功

## 10. 建议的处理流程

建议 `thread/message/send` 的流程如下：

1. 解析 `from_thread` 与 `to_thread`
2. 校验同实例范围内目标 thread 唯一
3. 检查目标 thread 是否被其他实例持有 live runtime
4. 若是，直接 fail-close，不写入 mailbox
5. 若否，持久化 mailbox message
6. 若目标 thread 当前空闲且可执行，尝试 wake
7. 若目标 thread 当前忙碌，则返回 `stored + pending_target_busy`
8. 目标 thread 后续空闲时，再由 service 自动补一次 wake

这里建议把“自动补 wake”也视为 service 内部实现，不额外让用户参与。

## 11. 分期建议

### 11.1 第一阶段

只做：

- 同实例
- thread-scoped mailbox
- `thread/message/send`
- 结构化回执
- 忙碌时 pending
- 当前实例自动补 wake

不做：

- 跨实例
- 联系人别名注册表
- 复杂批量 fan-out
- 可视化线程拓扑

### 11.2 第二阶段

若第一阶段稳定，再考虑：

- sender-thread scoped contacts / aliases
- inbox / outbox 查看面
- 回复链路与 `reply_to_message_id`
- skill 包装层

## 12. 明确不建议的方向

当前不建议：

- 继续把 binding 当作线程间通信的唯一锚点
- 把大段自然语言 prompt body 当成唯一 durable 消息事实
- 做跨实例 best-effort 投递
- 在没有清晰 runtime owner / interaction owner 语义前，直接让 service 偷偷代跑任意线程

## 13. 后续应落入正式文档的位置

若后续开始实现，建议把本文拆分下沉到：

- `docs/contracts/`
  - thread-to-thread 通信合同
  - delivery / wake / receipt 状态定义
- `docs/decisions/`
  - 为什么只支持同实例
  - 为什么采用 mailbox 而不是 binding-first synthetic prompt
- `docs/contracts/focusctl-command-matrix.zh-CN.md`
  - 新增 CLI 命令面

在真正实现前，本文仍只是 `_work` 草案。
