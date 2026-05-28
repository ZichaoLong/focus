# Goal 执行约束：Feishu Fast-ACK 收敛 — 2026-05-28

Status: working material under `docs/_work/`. Not a repository fact.

本文是本轮 goal 的短版执行约束文档。

它只保留：

- 本轮要做什么
- 不能做什么
- 统一交互模型是什么

背景调查、上游行为分析、恢复矩阵推导，见：

- `docs/_work/goal-resume-recovery-matrix-2026-05-28.zh-CN.md`

---

## 1. 本轮目标范围

本轮只收敛以下 Feishu 卡片重动作的交互模型：

1. `goal_apply_confirm(active)`
2. `resume_thread`
3. `attach_runtime` scope=`binding`
4. `attach_runtime` scope=`thread`
5. `attach_runtime` scope=`service`

当前明确不纳入：

1. `reset_backend`
2. 通用卡片动作异步化
3. 通用取消 / 覆盖 / revision 语义
4. 严格重复点击去重

---

## 2. 统一交互模型

本轮统一采用：

- fast ack = 原卡轻量 ACK patch
- completed = 后台新发结果卡
- failed = 后台新发失败卡

明确不采用：

- callback 直接返回最终结果卡
- 完成后再 patch 原卡为终态
- 假 attached
- 只靠 `thread/read` 或本地持久化状态把 binding 改成 `attached`

### 2.1 ACK 态要求

点击按钮当下，callback 只做：

- 极轻量参数校验
- 原卡 ACK patch

ACK patch 只表达：

- 已接收
- 后台处理中

ACK patch 不表达：

- 最终成功
- 最终失败
- 最终 attached / resumed / switched 状态

### 2.2 终态要求

真正完成后：

- 成功：主动发送结果卡
- 失败：主动发送失败卡

completed / failed 不再依赖 callback 生命周期。

---

## 3. 状态层硬约束

### 3.1 所有真实状态修改必须回到同一个 `RuntimeLoop`

fast-ack 只能改变：

- 飞书 callback 如何快速回执

不能改变：

- 真正状态修改的串行执行模型

因此必须继续保证：

- attach / resume / settings sync / goal 恢复仍回到同一个实例级 `RuntimeLoop`
- 不引入多线程并发写 runtime state

### 3.2 不做假 attached

`attached` 不是本地 UI 标记，而是：

- 当前 Feishu 服务进程已经真实恢复该 thread 的 backend 订阅事实

因此禁止：

- 只凭 `thread/read`
- 只凭持久化 binding 状态
- 只凭“thread 当前 loaded”

就把 binding 改成 `attached`

### 3.3 不引入覆盖语义

本轮不做：

- 新动作取消旧动作
- 后意图覆盖前意图
- 通用 revision / cancellation

只接受：

- 动作按进入 `RuntimeLoop` 的顺序串行执行

---

## 4. 动作级合同

### 4.1 `goal_apply_confirm(active)`

- 允许 fast-ack
- ACK：原卡 patch 成“正在恢复 goal…”
- 后台执行现有恢复矩阵
- 完成后新发结果卡

### 4.2 `resume_thread`

- 允许 fast-ack
- ACK：原卡 patch 成“正在恢复线程…”
- 后台执行真实 `resume_thread_on_runtime(...)`
- 完成后新发“已切换线程”卡或历史预览卡

### 4.3 `attach_runtime` scope=`binding`

- 允许 fast-ack
- ACK：原卡 patch 成“正在恢复当前会话推送…”
- 后台执行真实 attach
- 完成后新发当前会话 attach 结果卡

### 4.4 `attach_runtime` scope=`thread`

- 允许 fast-ack
- ACK：原卡 patch 成“正在恢复当前线程推送…”
- 后台执行 thread 级真实 attach
- 完成后新发 thread 级结果卡

### 4.5 `attach_runtime` scope=`service`

- 允许 fast-ack
- ACK：原卡 patch 成“正在恢复当前实例推送…”
- 后台执行实例级批量 attach
- 允许部分成功、部分 blocked
- 完成后新发实例级汇总结果卡

### 4.6 `reset_backend`

本轮不改。

理由：

- 当前主要痛点不在 reset 本身
- 当前主要痛点在 reset 之后的 attach
- 若 reset 结果卡本来就能稳定返回，则优先保持现状

---

## 5. 展示层风险接受

本轮接受以下展示层现象：

1. 因重复提交而产生的重复结果展示
2. `accepted` 时的上下文与 `completed` 时的真实结果可能不同
3. `service attach` 结果可能是部分成功、部分 blocked

本轮不接受以下状态层风险：

1. 并发写 runtime state
2. 假 attached
3. callback 超时后丢失最终结果

---

## 6. 建议实施顺序

1. 先把 `goal_apply_confirm(active)` 从“ACK patch + 后台结果卡”彻底收敛
2. 再实现 `resume_thread`
3. 再实现 `attach_runtime` scope=`binding`
4. 再实现 `attach_runtime` scope=`thread`
5. 最后实现 `attach_runtime` scope=`service`

这样可以先验证：

- callback 超时是否消失
- 后台结果卡链路是否稳定
- 单动作模型是否足够清晰
