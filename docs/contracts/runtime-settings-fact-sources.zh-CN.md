# 运行时设置的事实源与生效边界

英文原文：`docs/contracts/runtime-settings-fact-sources.md`

本文定义一套共享分析框架，用来回答这类问题：

- 某个设置“写入时”到底按什么解析？
- 写完以后，哪一层才是持久化事实源？
- 它会在什么边界真正被上游吃进去？
- 当前界面读到的值，到底是在读“持久化设置”、还是“live runtime”？
- 这个值现在到底只是“已记录”，还是“已经生效”？

如果不先区分这些问题，就很容易把“刚刚设置了什么”“下次会带什么”“当前 live
runtime 正在用什么”混成一件事。

## 1. 适用范围

当前项目里，运行时相关设置至少分成两大类：

- **thread-wise next-load state**
- **frontend-owned runtime settings**

这两类都可能被用户表面上理解成“设置”，但它们的事实源、生效边界、读回方式并不相同。

本文只定义共享分析框架，不取代各自的业务语义合同：

- thread-wise next-load 共享规则：`docs/contracts/thread-next-load-settings-semantics.zh-CN.md`
- 运行时控制面 / 飞书侧 runtime settings：`docs/contracts/runtime-control-surface.zh-CN.md`

## 2. 五个问题，一个阶段标记

判断任一运行时设置时，至少要分别回答下面五个问题，并额外标记它是否仍处在 provisional 阶段。

### 2.1 写时解析源

这是“用户此刻发出设置请求时，系统按什么规则把目标值解析出来”。

它回答的是：

- 用户到底想设成什么？
- 有没有先把简写、别名、组合命令展开？
- 有没有先补全成一份完整可写入的目标值？

### 2.2 写后持久源

这是“写入动作成功返回后，哪一层记录成为后续的持久化事实源”。

它回答的是：

- 后续重读时该看哪里？
- 这次写入到底落到了 thread 级、binding 级，还是只是临时 pending 状态？

### 2.3 应用边界

这是“哪一次正式上游边界会真正消费这份设置”。

典型边界包括：

- `thread/start`
- `thread/resume`
- `turn/start`

“已写入”不等于“已被某个 live runtime 吃进去”。

### 2.4 读侧视图

这是“当前某个读接口 / 状态页 / 调试面读到的是什么层次的值”。

它回答的是：

- 这是下一次 load/turn 的意图值？
- 这是某次 load 时观测到的 snapshot？
- 还是当前 live runtime 的权威真相？

如果读侧没有足够权威，就必须承认“当前无法稳定读回 live 真相”。

### 2.5 生效判定

这是“这份设置是否已经越过其应用边界，被真实运行时消费”。

它回答的是：

- 现在只是 persisted intent
- 还是已经成为下一次 load / turn 会用的输入
- 还是已经被当前 live runtime 实际吃进去

### 2.6 provisional / pending 阶段

有些时刻，上面五个问题并不能都给出稳定答案。

典型例子：

- `thread_id` 还没 materialize
- `thread/start` 结果未知
- pending seed 还没 promote 成正式 thread-wise persist state

这时必须明确标记：

- 当前仍是 **provisional / pending**

而不是把一个临时 seed 假装成正式持久化真相。

## 3. thread-wise next-load state

这类设置的共享规则由
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 定义；本文只把它放进统一事实源框架里。

### 3.1 写时解析源

- 目标值先按各自 setting 合同解析成 thread-stable 目标值
- profile 这类 slice，必须先解析成完整有效的三元组：
  `profile`、`model`、`model_provider`
- memory 这类 slice，必须先归一化成合法枚举值

### 3.2 写后持久源

正常 thread 上，正式持久源是：

- thread-wise profile store
- thread-wise memory store

但在 provisional 阶段要区分：

- launch seed
  - 还没有 `thread_id`
  - 只是当前会话级 one-shot seed
- pending threadwise seed
  - 已绑定 `thread_id`
  - 但还不是正式 thread-wise persist state

只有在首个成功用户 turn 完成后，pending seed 才能 promote 为正式 thread-wise 持久化事实。

### 3.3 应用边界

这类设置的应用边界是：

- unloaded -> loaded 的线程边界
- 也就是受支持路径上的 `thread/start` / `thread/resume`

它们不是 turn-time hot override，也不是对已 loaded runtime 的原地热改。

### 3.4 读侧视图

对 **unloaded** thread：

- thread-wise 持久化 store 是事实源

对 **loaded** thread：

- live runtime 才是当前真相
- 本项目当前稳定可读的，只是 `thread/start` / `thread/resume` 返回里的
  **load-time observed snapshot**

对 **provisional** thread：

- launch seed / pending seed 只代表待 materialize 的意图
- 不能把它当成正式 persisted thread truth

### 3.5 生效判定

这类设置只有在满足下列条件时，才算已经生效：

- 目标 thread 处于 unloaded
- 后续有一次受支持的 `thread/start` / `thread/resume`
- 那次 load 实际消费了该持久化 thread-wise state

因此：

- “已直接写入 thread-wise store” 只表示 next-load 会使用它
- 不表示当前某个已 loaded runtime 已被就地改掉

## 4. frontend-owned runtime settings

这类设置的飞书侧产品合同由
`docs/contracts/runtime-control-surface.zh-CN.md` 定义；本文只定义它在共享框架下应怎样理解。

### 4.1 写时解析源

飞书侧的这类设置，写时先按当前 binding 的命令合同解析。

例如：

- `/model` 解析为 model 覆盖项
- `/effort` 解析为 reasoning effort 覆盖项
- `/approval` 与 `/sandbox` 解析为各自 runtime 字段
- `/permissions` 不是独立 persisted 字段，而是先展开成
  `approval_policy + sandbox`

### 4.2 写后持久源

飞书侧这类设置的持久源是：

- 当前 Feishu binding 上的 persisted settings

必要时还会同步刷新服务内存里的 binding runtime state，但它仍然是 binding 级事实，不是 thread 级事实。

### 4.3 应用边界

这类设置当前主要在下面的边界被消费：

- 当前 binding 发起 `thread/start`
- 当前 binding 发起 `turn/start`

因此：

- 在某轮 turn 真正开始前改动，可能立刻影响这一轮
- 若该轮 turn 已经运行中，则通常从下一轮生效

### 4.4 读侧视图

这类设置的读侧视图，默认应理解成：

- 当前 binding 的 next-turn intent

例如 `/status` 或对应设置页显示的值，回答的是：

- “这个 Feishu 会话下一次由自己发起 turn 时，准备注入什么”

它不回答：

- 另一个 Feishu 会话会注入什么
- 本地 `fcodex` 会注入什么
- 当前已 loaded thread 的完整 live runtime 真相是什么

### 4.5 生效判定

这类设置只有在后续真的发生了相应 binding 发起的 `thread/start` 或 `turn/start`，并把这些字段送入上游时，才算被运行时消费。

因此：

- “binding 上已保存设置” 不等于“当前 loaded thread 就正在按它运行”
- 它更接近“下一次由这个 binding 发起的 load / turn 的输入意图”

## 5. provisional thread 与 pending seed 的正式位置

当前仓库必须明确承认：

- provisional 阶段存在
- pending seed 存在
- 它们不是正式 persisted thread-wise truth

应区分三层：

1. launch seed
   - 会话级 one-shot seed
   - 还没有 thread 身份
2. pending threadwise seed
   - 已经绑定 `thread_id`
   - 仍在等待首个成功 turn promote
3. promoted thread-wise state
   - 才是后续恢复路径的正式 thread-wise 持久化事实

这条区分同样影响“是否生效”的判断：

- provisional / pending 阶段，通常只能说“已记录意图”
- 不能直接说“该 thread 现在已经正式带有这份 persist state”

## 6. 实操读法

当用户问“现在到底是什么”时，必须先把问题归类：

- 问“刚刚设置成什么”
  - 看写时解析源
- 问“持久化记住了什么”
  - 看写后持久源
- 问“下次 thread load 会用什么”
  - 看 thread-wise next-load state
- 问“这个飞书会话下一轮 turn 会带什么”
  - 看当前 binding 的 frontend-owned runtime settings
- 问“当前 live runtime 正在用什么”
  - 优先看 live runtime / load-time snapshot
  - 如果当前合同没有稳定读面，就应明确回答 unknown，而不是拿持久化值冒充 live 真相
