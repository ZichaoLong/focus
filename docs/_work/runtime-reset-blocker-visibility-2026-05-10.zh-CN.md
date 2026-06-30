# reset-backend 阻塞信息展示建议 - 2026-05-10

范围：

- 飞书侧 `/profile` / `/memory` / `/reset-backend`
- 本地 `focusctl thread memory`
- 本地 `fcodex resume <thread> -p <profile>`
- 目标：把“为什么现在要不要重置 backend”讲清楚，但不要把卡片和 CLI 输出做成线程列表洪水

## 1. 结论

建议把阻塞信息分成两层：

1. `hard blocker`
   - 直接决定“这次能不能立即 reset / 立即改写”的事实
2. `collateral impact`
   - reset 之后会受影响、但通常可自动恢复或可通过 service 级 reattach 收口的其他线程

其中：

- `active turn` 应该是最高优先级 blocker
- `pending request` / 审批请求次之
- `attached binding` 与本地 `fcodex` holder 也应显示
- 其他 `loaded threads` 只给摘要，不要默认全列

这更像 Windows 的重启提示：

- 用户先看到“谁在阻塞”
- 再看到“哪些东西会一起受影响”
- 然后自己判断要不要现在重置

## 2. 飞书侧建议

### 2.1 主卡片结构

建议卡片保持三段：

1. 结论行
   - 例如：`当前 thread 仍处于 loaded，因此不能直接改写 profile / memory mode`
2. Hard blocker 区
   - `active turn`
   - `pending request`
   - `attached bindings`
   - `fcodex holder`
3. Collateral impact 区
   - 当前实例上其他 loaded threads 的数量
   - 其中有 active turn 的数量
   - 需要展开时再看具体条目

### 2.2 不建议的做法

不建议在主卡片里直接把所有 loaded threads 展开成完整列表，原因是：

- 信息过多
- 读者真正关心的是“有没有正在进行中的工作”
- 大量已 loaded 但无 active turn 的线程，往往可在 reset 后自动 resume，或者可通过 service 级 reattach 再收口

### 2.3 推荐展示优先级

建议按下面顺序排：

1. `active turn`
2. `pending request`
3. `fcodex holder`
4. `attached bindings`
5. `其他 loaded threads`

原因：

- `active turn` 最接近“现在会不会真的打断工作”
- `pending request` 最接近“现在会不会漏掉待处理输入”
- `fcodex holder` 说明本地 TUI 仍在持有 live runtime
- `attached binding` 说明还有 Feishu 会话在挂着

## 3. 本地侧建议

本地也应该有对应信息，而且更适合细一点。

### 3.1 本地输出建议分两层

1. `hard blocker`
   - 当前 thread 的 `active turn`
   - `pending request`
   - 本地 `fcodex` holder
   - 当前绑定侧 `attached binding`
2. `collateral impact`
   - 当前实例上其他 loaded threads
   - 只给数量和前几条

### 3.2 本地为什么更需要

因为本地用户更常真的要决定：

- 现在直接 `reset-backend`
- 还是先把某个本地 `fcodex` 窗口处理完
- 或者先等某个 active turn 结束

所以本地不只是“告知失败”，还要帮人做操作判断。

## 4. 数据结构建议

建议不要把“阻塞信息”变成新的 reason_code 爆炸，而是保持主判定简单，附加诊断字段。

主判定仍然只保留：

- `unbound`
- `loaded`
- `runtime_unverified`

但在结果里附加：

- `blocking_instance`
- `blocking_holder_labels`
- `blocking_binding_ids`
- `blocking_active_turn_count`
- `blocking_pending_request_count`
- `collateral_loaded_thread_count`
- `collateral_loaded_thread_preview`

其中：

- `blocking_holder_labels` 可包含 `service@instance`、`fcodex@instance(pid=...)`
- `blocking_binding_ids` 用于飞书侧说明“哪些会话挂着”
- `blocking_active_turn_count` 应单独暴露，不要混在 `loaded` 里
- `collateral_loaded_thread_preview` 只保留前几条，避免卡片爆炸

## 4.1 语义校准

不要把“看起来重要”直接等同于“真正阻塞 reset”。

更准确的拆法是：

- `hard blocker`
  - 直接决定本次是否必须 `force reset` 或直接拒绝的事实
  - 例如 `active turn`、`pending request`、`runtime verification failed`
- `impact facts`
  - 说明 reset 之后会受影响、但不一定阻止本次 reset 的事实
  - 例如 `attached binding`、`fcodex holder`、其他 `loaded threads`

因此：

- `attached binding` 和 `fcodex holder` 更适合优先出现在 `impact facts` 或“次级诊断”里
- 如果要把它们放进主卡片，也应避免直接把区块标题写成绝对的 `Hard Blockers`
- 区块标题如果保留 `Hard Blockers`，内容就应该和状态机的强约束完全一致

这条尤其重要，因为：

- `attached binding` 可能只是说明“会被影响”
- 但并不必然说明“本次不能 reset”
- 如果把它们都算成 blocker，容易让 `available` / `force-only` 的预览状态和卡片标题打架

## 5. 语义边界

建议明确一条原则：

- `fcodex` 作为 blocker 时，应该被当作“诊断事实”
- 不要把它写成唯一动作建议

也就是说：

- 飞书卡片可以告诉用户：`当前有本地 fcodex 仍在持有`
- 但真正主动作仍然是：`reset-backend`
- 不要让用户误以为“先关掉 fcodex 就能立即生效”

因为现实里：

- 关掉 `fcodex` 只是让 future unload 更接近成立
- 并不等于现在就已经 globally unloaded
- 用户真正想要的常常还是“立即重置”

## 6. 推荐文案模板

### 6.1 主卡片

> 当前 thread 仍处于 loaded，不能直接改写。
> 
> hard blocker:
> - active turn: 1
> - pending request: 0
> - fcodex holder: fcodex@default(pid=12345)
> - attached bindings: p2p:ou_xxx:chat_yyy
>
> collateral impact:
> - loaded threads on this instance: 5
> - active turns among them: 1
> - preview: thread-a, thread-b, thread-c

### 6.2 本地 CLI

> 当前 thread 仍由实例 `default` 保持为 loaded。
> hard blocker: active turn=1, pending request=0, fcodex@default(pid=12345)
> collateral impact: loaded threads=5, active turns=1

## 7. 直接建议

如果后续要实现，我建议按这个顺序：

1. 先把 `active turn` 和 `pending request` 补进 blocker 诊断
2. 再补 `fcodex holder` / `attached binding`
3. 最后补 `collateral impact` 的摘要和可展开详情

这样能先得到最有价值的信息，不会一开始就把状态机和 UI 一起做重。
