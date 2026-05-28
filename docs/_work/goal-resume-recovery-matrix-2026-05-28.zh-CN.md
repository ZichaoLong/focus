# `/goal resume` 恢复矩阵与实现方案 — 2026-05-28

Status: working material under `docs/_work/`. Not a repository fact.

本文记录当前 `feishu-codex` 在 `/goal resume`、`/attach`、`thread/resume`、
binding-wise runtime settings 与上游 goal 自动续跑之间的真实关系，并给出后续可落地的恢复矩阵与实现方案。

本文不是正式合同。它的作用是：

- 把这轮分析结论固定下来，避免后续再把 `thread/resume`、`thread/settings/update` 与 `goal resume` 混成一件事
- 给后续修复 `/goal resume` 权限不生效问题提供一份明确的状态矩阵
- 给“飞书卡片 action 回调超时”提供一条工程上可执行的修复路径

另见：

- `docs/contracts/feishu-thread-lifecycle.zh-CN.md`
- `docs/contracts/runtime-settings-fact-sources.zh-CN.md`
- `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`
- `docs/_work/runtime-permissions-profile-migration-2026-05-28.zh-CN.md`

---

## 1. 当前已确认事实

### 1.1 普通 prompt 路径会注入飞书 binding 的 next-turn 设置

当前普通消息发起 turn 时，会把当前 binding 上的：

- `approval_policy`
- `permissions_profile_id`
- `reasoning_effort`
- `collaboration_mode`

作为 turn-time override 注入上游。

相关实现：

- `bot/prompt_turn_entry_controller.py`

这条路径的语义是：

- 这些设置属于 **binding-wise next-turn intent**
- 它们不是 thread-wise next-load setting

### 1.2 `/goal resume` 在 detached 场景下不走普通 prompt 路径

当前飞书侧 `/goal resume` 若命中 detached 确认卡，会同步执行：

1. `attach_current_binding(...)`
2. `thread/resume`
3. `thread/goal/set(status="active")`

相关实现：

- `bot/codex_goal_domain.py`
- `bot/codex_handler.py`

这意味着：

- `/goal resume` 当前不是“下一条普通消息触发 turn”
- 它当前是一个 control-plane 恢复路径

### 1.3 当前本项目的 `thread/resume` 恢复链路没有注入 binding-wise permission 设置

当前 `_resume_snapshot_by_id(...)` 调用 adapter 的 `resume_thread(...)` 时，只带：

- `profile`
- `config_overrides`
- `model`
- `model_provider`

没有带：

- `approval_policy`
- `permissions_profile_id`

所以：

- 重启服务后，飞书侧直接 `/goal resume`
- 会先 attach / `thread/resume`
- 但 app-server 在 resume 阶段拿不到当前飞书 binding 的 permission 设置

这正是用户实际观察到“直接 `/goal resume` 时 permission 不生效，但手动再发一条 prompt 就恢复正常”的主因。

### 1.4 上游 `thread/resume` 与 `thread/settings/update` 是两条不同语义的路径

上游当前至少有两条相关路径：

1. `thread/resume`
- 负责 materialize / rejoin thread
- 可接受部分 override

2. `thread/settings/update`
- 负责更新 loaded thread 的 subsequent-turn settings
- 当前 canonical 地支持：
  - `approval_policy`
  - `permissions`
  - `model`
  - `effort`
  - `collaboration_mode`
  - 等等

这两条路径不能视为等价：

- `thread/resume` 不能替代 `thread/settings/update`
- `thread/settings/update` 也不能替代 cold `thread/resume`

### 1.5 上游对 loaded thread 的 `thread/resume` override 会忽略一部分字段

对已 running / loaded 的 thread，上游 `thread/resume` 更偏 rejoin 语义。

当前上游会：

- 检查 `resume` 请求里的 override 是否与 active config 不一致
- 若不一致，则记录 mismatch
- `permissions` 会被明确视为“provided and ignored while running”

因此：

- 对 loaded thread，不能把 `thread/resume` 当成稳定的 settings 注入接口
- 对 loaded thread，canonical 修正路径应是 `thread/settings/update`

### 1.6 上游在 `thread/resume` 后会自动继续 active goal

上游 app-server 当前在 resume 成功后会调用：

- `continue_active_goal_if_idle()`

因此：

- 如果 thread 上持久化 goal 当前状态是 `active`
- 单纯 `thread/resume` 就可能让 goal 自动继续

相反：

- 如果 goal 当前是 `paused`
- `thread/resume` 不会自动把它改成 `active`

### 1.7 `/goal` 读到的状态主源来自上游，不只是飞书本地缓存

当前飞书侧 `/goal` 会主动调用：

- `thread/goal/get`

并且 app-server 也会通过：

- `thread/goal/updated`
- `thread/goal/cleared`

持续刷新本地 runtime projection。

因此：

- `/attach` 后即使尚未手动 `/goal resume`
- `/goal` 仍可能显示 `active`
- 这通常是上游 thread goal 的真实状态，不是飞书本地幻觉

---

## 2. 三类恢复情形

虽然表面上可以把 `/goal resume` 看成“两类”：

1. thread 已 loaded
2. thread 未 loaded，需要先 `thread/resume`

但若要判断 permission 设置能否及时生效，必须进一步细分成三类情形：

1. loaded thread
2. cold resume + paused goal
3. cold resume + active goal

真正的关键差别不是只有 loaded / unloaded，而是：

- goal 在恢复前是 `paused`
- 还是已经是 `active`

因为这决定了 app-server 会不会在 `thread/resume` 之后立刻自动续跑。

---

## 3. 恢复矩阵

| 场景 | thread 当前状态 | goal 恢复前状态 | app-server 是否会在 `thread/resume` 后自动续跑 | 想让“恢复出来的第一轮”吃到飞书 binding 的 permission 设置，推荐路径 |
| --- | --- | --- | --- | --- |
| A | loaded | paused | 否 | `thread/settings/update` -> `thread/goal/set(active)` |
| B | loaded | active | 已 active，通常不需要额外 `goal/set`；若要显式纠偏，也应先 `thread/settings/update` 再处理后续 turn | 不依赖 `thread/resume`；对 loaded thread 直接走 `thread/settings/update` |
| C | unloaded | paused | 否 | `thread/resume` -> `thread/settings/update` -> `thread/goal/set(active)` |
| D | unloaded | active | 是 | 若要求“自动续跑的第一轮”也吃到设置，必须在 cold `thread/resume` 本身带上 `approval_policy` / `permissions`；单靠事后 `thread/settings/update` 太晚 |

### 3.1 场景 A：loaded thread + paused goal

这是最干净的一类。

因为：

- thread 已 loaded
- goal 未自动运行

所以可以稳定按下面的顺序做：

1. `thread/settings/update`
2. `thread/goal/set(status="active")`

结果：

- 恢复出来的第一轮 goal turn 能吃到新的 binding-wise settings

### 3.2 场景 B：loaded thread + active goal

这种情况下重点不是“resume thread”，而是：

- 当前 loaded runtime 的后续 turn 该吃什么设置

这时不应依赖 `thread/resume`。

如果当前 thread 仍 idle，但 goal 状态已经 active，则：

- 可先 `thread/settings/update`
- 随后让上游继续自己的 active-goal 续跑逻辑

若前端还要做显式恢复动作，也应把它视为：

- 对当前 loaded runtime 的 settings 纠偏

而不是“重新 resume 一次 thread”。

### 3.3 场景 C：unloaded thread + paused goal

这类场景不需要和 app-server 抢时序。

因为：

- `thread/resume` 不会自动续跑 paused goal

所以可用顺序是：

1. `thread/resume`
2. `thread/settings/update`
3. `thread/goal/set(status="active")`

结果：

- 第一轮恢复出来的 goal turn 仍可吃到更新后的 settings

### 3.4 场景 D：unloaded thread + active goal

这是最棘手的一类，也是当前用户问题最容易命中的一类。

因为：

- cold `thread/resume` 会把 thread materialize 回来
- app-server 随后可能立刻 `continue_active_goal_if_idle()`

若这时本项目还没来得及发：

- `thread/settings/update`

那么自动续跑出来的第一轮，很可能仍按：

- thread 原先持有的 live settings
- 或 app-server 默认/历史设置

运行，而不是按当前飞书 binding 的 permission 设置运行。

所以，对场景 D：

- 如果产品要求保留“cold resume 后 active goal 自动续跑”的现状
- 且又要求“自动续跑的第一轮”必须吃到当前飞书 binding 设置

那么本项目就必须在 cold `thread/resume` 请求本身里带上：

- `approval_policy`
- `permissions`

之后再补一条 `thread/settings/update`，把 subsequent-turn settings 与当前 binding 对齐。

---

## 4. 当前用户现象如何落到矩阵上

用户当前观察到的问题是：

- 重启 `feishu-codex` 服务
- 飞书会话仍绑定在某个有 goal 的 thread 上
- 直接执行 `/goal resume`
- permission 设置未生效，仍弹文件修改审批
- 但手动再发一条 prompt 后，goal 后续又恢复到期望权限

这通常命中的是：

- 场景 D：unloaded thread + active goal

其现状解释是：

1. 服务重启后，本项目侧 binding hydrate 为 detached
2. `/goal resume` 触发 attach -> `thread/resume`
3. 当前本项目没有在 `thread/resume` 时传 `approval_policy` / `permissions`
4. app-server cold resume 成功后，active goal 自动续跑
5. 这第一轮 goal 没吃到飞书会话级 settings
6. 后来用户再手动发一条普通消息
7. 普通 prompt 路径经 `turn/start` 注入 binding-wise settings
8. 于是后续 turn 的权限才恢复正常

---

## 5. 建议的后续实现方案

## 5.1 目标

目标不是简单“把参数补全”，而是同时满足：

- 语义不混乱
- loaded thread 与 cold resume 都有清晰路径
- `/goal resume` 不再因为服务重启而丢失 binding-wise permission 设置
- 飞书卡片 action 不再因重活同步执行而频繁超时

## 5.2 实现原则

### 原则一：保持概念分层

应继续区分：

- thread-wise next-load state
- binding-wise next-turn settings
- goal active/paused state

不能把它们产品上揉成一个“resume 什么都顺带做好”的单一概念。

### 原则二：对 loaded thread，settings 修正走 canonical `thread/settings/update`

loaded thread 的 permission 修正，不应依赖 `thread/resume`。

这是上游当前的 canonical 路径。

### 原则三：对 cold resume + active goal，允许在 `thread/resume` 本身带 permission override

这是为了保证：

- 自动续跑的第一轮也吃到当前飞书 binding 的 settings

如果不这样做，就必须改产品行为，让 cold resume 后不再自动继续 active goal。

### 原则四：卡片 action 回调不应同步承担耗时恢复工作

飞书 action callback 应只做：

- 快速 ACK
- 轻量参数校验

真正的 attach / resume / settings sync / goal resume 应转后台异步执行。

---

## 6. 推荐落地步骤

### 6.1 步骤一：扩展 adapter 的 resume 接口

给本项目 adapter 的 `resume_thread(...)` 扩展参数：

- `approval_policy`
- `permissions_profile_id`

并让 app-server adapter 在 `thread/resume` 时按上游当前 canonical 字段发送：

- `approvalPolicy`
- `permissions`

这一步主要服务于：

- 场景 D

实现这一步时，必须明确补上代码注释，并在设计说明中坚持以下解释：

- 这里传入的不是 thread-wise persisted resume metadata
- 也不是把 binding-wise next-turn settings 升格为 thread-wise setting
- 它只是利用上游 `thread/resume` 在 cold resume 场景下可接受 runtime override 的能力
- 目的是让 cold resume 后 app-server 自动续跑的第一轮，也能尽量对齐当前飞书 binding 的权限意图

因此，后续实现必须继续保持：

- loaded thread 的 canonical 修正路径仍是 `thread/settings/update`
- thread-wise next-load state 与 binding-wise next-turn settings 仍是两套不同概念
- `resume_thread(..., approval_policy, permissions_profile_id)` 不能被读成“resume 本身拥有一份新的 thread-wise 设置合同”

### 6.2 步骤二：新增 `thread/settings/update` 封装

在 adapter 层增加显式方法，例如：

- `update_thread_settings(...)`

至少覆盖：

- `approval_policy`
- `permissions_profile_id`
- 未来可顺手容纳 `model` / `reasoning_effort` / `collaboration_mode`

这一步主要服务于：

- 场景 A
- 场景 B
- 场景 C
- 以及场景 D 的 subsequent-turn 对齐

### 6.3 步骤三：在控制面恢复时显式分流

恢复逻辑建议按下面的高层顺序实现：

1. 先判断当前目标 thread 是 loaded 还是 unloaded
2. 再读取当前 thread goal 状态
3. 按矩阵选择恢复顺序

推荐顺序：

- loaded + paused
  - `thread/settings/update`
  - `thread/goal/set(active)`

- loaded + active
  - `thread/settings/update`
  - 不必再多做一次 `thread/resume`

- unloaded + paused
  - `thread/resume(with binding permission overrides optional but not required)`
  - `thread/settings/update`
  - `thread/goal/set(active)`

- unloaded + active
  - `thread/resume(with approval_policy + permissions)`
  - `thread/settings/update`
  - 不再额外触发重复的 active 恢复动作，避免与 app-server 自动续跑打架

### 6.4 步骤四：把 goal 卡片确认动作改成异步 ACK

当前 `goal_apply_confirm` 不应继续同步执行完整恢复链路。

建议改成：

1. action callback 立即返回
   - toast：`已接收，后台处理中`

2. 后台任务执行：
   - attach
   - `thread/resume` / `thread/settings/update`
   - `goal resume`

3. 完成后再：
   - patch 原确认卡
   - 或发送一张结果卡

这样可解决：

- rollout 很大时 `thread/resume` 过慢
- 飞书同步 action callback 超时
- 用户先看到“目标回调服务超时未响应”，但后台其实稍后又成功的混乱体验

---

## 7. 为什么单靠 `thread/settings/update` 不够

若只从“配置语义更干净”考虑，很容易得出：

- 有 `thread/settings/update` 了，就不必在 `thread/resume` 带 permission override

这个结论只对部分场景成立。

它成立的前提是：

- 目标 goal 不会在 `thread/resume` 成功后立刻自动续跑

也就是只对以下场景天然成立：

- loaded thread
- paused goal

而对：

- unloaded + active goal

它不成立，因为：

- `thread/settings/update` 发生在 `thread/resume` 之后
- app-server 可能已先启动 active goal 的第一轮

所以：

- `thread/settings/update` 不能完全替代 cold `thread/resume` override
- 它只能替代 loaded thread 的 settings 修正，或 paused-goal 恢复链路里的 settings 注入

---

## 8. 是否可以改成“不让 app-server 自动恢复 active goal”

理论上可以，但这是产品行为改变。

若要这样做，新的语义将变成：

- `thread/resume` 只负责 attach / materialize
- 即使 goal 当前是 `active`，飞书侧也先不让它自动继续
- 前端在 settings 对齐后，再显式决定是否恢复 goal

这样做的优点是：

- 语义最整洁
- 不再需要在 cold `thread/resume` 上特殊补 permission override

代价是：

- 会改变当前用户已经观察到的行为
- 也会与上游 app-server 当前“resume 后自动继续 active goal”的内建语义产生偏差

因此在当前阶段，不建议把它当成本项目的第一步修复方案。

---

## 9. 回调超时的结论

“目标回调服务超时未响应”不是权限不生效的主因，但它是一个真实 UX bug。

它的根因不是某个单一异常，而是：

- 飞书卡片 action callback 的同步时限较短
- `thread/resume` 对大 rollout 可能天然较慢
- 当前实现又把 attach / resume / goal-resume 都堆进同步回调里

因此：

- 这个 toast 不是无解
- 但不能靠继续缩短代码路径或侥幸提速来解决
- 正确修法是把重活从同步 callback 中移走

---

## 10. 本文约束的后续工作

后续若实现 `/goal resume` 修复，至少应满足：

1. 明确区分 loaded / unloaded 与 paused / active
2. 对 loaded thread 的 settings 修正走 `thread/settings/update`
3. 对 unloaded + active goal，第一轮若要求吃到 binding settings，则必须在 cold `thread/resume` 带 permission override
4. 不再把完整恢复链路同步压在飞书 action callback 里

若后续实现未满足这四点，则应视为：

- 仍未真正收敛 `/goal resume` 的恢复语义
- 或仍可能在某些恢复路径上继续丢失 permission 设置
