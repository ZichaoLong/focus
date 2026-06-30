# thread-wise memory control surface 审视记录 - 2026-05-10

范围：

- 最新 `HEAD`：`d224a5c Add thread-wise memory control surface`
- 审视重点：
  - `focusctl thread memory`
  - 飞书 `/memory` 与 `/profile`
  - `default_thread_memory_mode` 新线程 seed
  - 与上一轮 scheduled prompt 修复后的合同一致性

## 1. 结论摘要

本轮新增的 `thread/memory` 本地控制面总体方向是对的，但当前 `HEAD` 仍有三处值得优先处理的真实行为问题：

1. thread-wise memory override 在带 `profile_name_hint` 时会生成 `profiles.<name>.memories`，这和 upstream `ConfigProfile` 的实际 schema 不一致，存在把 `thread/start` / `thread/resume` 配置直接做成无效 payload 的风险
2. thread-wise next-load 设置缺少“同值写入”短路，导致 `/profile`、`/memory`、`focusctl thread memory` 都可能把 no-op 请求误判为需要 reset 的变更
3. `thread/memory` 成功写入后，返回结果仍携带变更前的 mutation plan / reason code，CLI 会打印相互矛盾的状态

另外还有一条较低优先级但应尽快收口的合同漂移：

4. `binding/submit-prompt` 现在已 fail-close 拒绝不存在的 binding，但 `scheduled-prompts` 合同文档还没把这条新边界写清楚

## 2. Findings

### P0: 带 `profile_name_hint` 的 thread-wise memory override 会生成 upstream 不支持的 profile 内 `memories` 字段

涉及代码：

- [bot/thread_memory_mode.py](../../bot/thread_memory_mode.py:51)
- [bot/fcodex_proxy.py](../../bot/fcodex_proxy.py:576)
- [bot/codex_handler.py](../../bot/codex_handler.py:2467)
- [bot/codex_handler.py](../../bot/codex_handler.py:2733)
- `codex-rs/config/src/profile_toml.rs:22`

当前行为：

1. `build_thread_memory_config_override()` 总会写顶层：
   - `memories.use_memories`
   - `memories.generate_memories`
2. 但只要带了 `profile_name_hint`，它还会额外写：
   - `profiles.<name>.memories.*`
3. 这个 `profile_name_hint` 不是边角路径才会出现，而是多个正式路径都会主动补：
   - `fcodex resume <thread>` 的 proxy 恢复路径
   - 飞书侧 `/memory` / `/profile` 后需要重新 seed config 的路径
   - `default_thread_memory_mode` 的新线程 seed 路径
4. upstream 顶层 `ConfigToml` 确实支持 `memories`
5. 但 upstream `ConfigProfile` 明确 `deny_unknown_fields`，且字段列表里没有 `memories`

也就是说，当前 override builder 实际在做两件事：

- 一件是合法的：写顶层 `memories`
- 一件是高风险的：把同样的内容再塞进 `profiles.<name>.memories`

为什么这是 correctness 风险：

- 这不是“语义可能不理想”，而是“生成出来的配置形状本身就可能不被 upstream 接受”。
- 一旦 app-server 严格按 `ConfigProfile` 解析这份 override，带 `profile_name_hint` 的路径就可能直接得到 invalid configuration。
- 由于 `profile_name_hint` 恰好出现在最常走的正式路径上，所以这不是低概率边角问题。

白话场景：

1. 某个 thread 已有 profile，或 `fcodex resume <thread>` 启动时 wrapper 已推断出 profile hint。
2. 该 thread 又恰好配置过 thread-wise memory mode。
3. proxy 在发 `thread/resume` 时，会把 memory mode 转成 config override。
4. 这份 override 不仅写了顶层 `memories`，还写了 `profiles.<当前 profile>.memories`。
5. upstream 如果严格校验 profile schema，这次 resume 不是“memory mode 没生效”，而是可能整个请求都被判成配置非法。

建议收敛方向：

1. `thread-wise memory mode` 的 override builder 不应再写 `profiles.<name>.memories`。
2. 这份 thread-wise next-load state 只应通过顶层 `memories` slice 表达。
3. 补一条回归测试，约束：
   - 生成的 `config_overrides` 必须符合 upstream 当前 config schema
   - 尤其不得向 `ConfigProfile` 注入未知字段

### P0: thread-wise next-load 设置没有 no-op 短路，可能导致无意义的 backend reset

涉及代码：

- `bot/codex_settings_domain.py:641`
- `bot/codex_settings_domain.py:696`
- `bot/codex_settings_domain.py:933`
- `bot/codex_settings_domain.py:981`
- `bot/runtime_admin_controller.py:1659`
- `bot/runtime_admin_controller.py:1704`

当前问题不是“写入失败”，而是“请求本来无需写入，却仍被当成变更处理”。

具体表现：

1. 飞书 `/profile <name>`
   - 先读取当前持久化 profile
   - 但后续只按 `plan.status` 决定是否需要 reset
   - 没有先判断 `target_profile == current_profile`
2. 飞书 `/memory <mode>`
   - 同样没有先判断 `target_mode == current_mode`
3. 本地 `focusctl thread memory --mode <mode>`
   - `thread_memory_mode_control_result()` 也没有对“目标值是否已等于当前持久化值”做短路
   - 因此 loaded thread 上的同值请求会直接进入 reset 计划分支

为什么这是 correctness bug：

- 这些设置的合同是 **thread-wise next-load 设置**
- 如果目标值已经等于当前持久化值，请求本质上是幂等查询，不应再触发变更收口逻辑
- 当前实现却可能：
  - 返回“需要 reset backend”
  - 在用户显式传了 `--reset-backend` / `--force-reset-backend` 后，真的执行一次没有必要的 backend reset
  - 打断当前实例中的其他工作

本地最小复现：

- 构造 `thread-1`
  - 当前持久化 memory mode 已是 `read`
  - 当前 backend thread status 为 `idle`
- 调用：
  - `thread/memory` + `mode=read`
  - 返回 `plan_status=reset-available`，`applied=false`
- 再调用：
  - `thread/memory` + `mode=read` + `reset_backend=true`
  - 会真的执行一次当前实例 backend reset，并返回 `applied=true`

这说明：

- 同值请求当前不是“no-op success”
- 而是“先提示 reset，再允许 destructive no-op”

建议收敛方向：

- 在所有 thread-wise next-load 设置入口统一加一条最前置短路：
  - 若请求值已等于当前持久化值，直接成功返回
  - 不进入 reset / force-reset 计划
- 这条短路应收敛成共享 helper，而不是分别散落在：
  - `/profile`
  - `/memory`
  - `thread/memory`

### P1: `thread/memory` 成功写入后仍返回旧的 mutation plan / reason code

涉及代码：

- `bot/runtime_admin_controller.py:1659`
- `bot/runtime_admin_controller.py:1668`
- `bot/runtime_admin_controller.py:1704`
- `bot/feishu_codexctl.py:415`

当前行为：

1. `thread_memory_mode_control_result()` 一开始先计算一次 `plan`
2. 把下列字段一次性写进结果：
   - `plan_status`
   - `reason_code`
   - `reason`
   - `requires_reset_backend`
   - `requires_force_reset_backend`
3. 后续即使执行了：
   - direct-write
   - 或 reset backend + apply
4. 结果里也只更新：
   - `thread_memory_mode`
   - `applied`
   - `backend_reset_performed`
   - `backend_reset_result`
   - 成功文案 `reason`
5. 但不会重新计算 `plan_status` / `reason_code` / `requires_reset_backend`

结果就是：

- 同一次成功操作会同时暴露两组相互矛盾的信息
- 例如：
  - `applied=true`
  - `backend_reset_performed=true`
  - 但 `plan_status` 仍是 `reset-available`
  - `reason_code` 仍是 `memory_mode_reset_available`

这不仅影响 CLI 文案，也会影响任何后续自动化：

- `focusctl` 会直接打印 `mutation plan: ...`
- 读这个控制面结果的脚本会看到一个“已成功写入，但仍声称还需要 reset”的状态

建议收敛方向：

- 成功写入后，要么：
  - 重新计算 fresh plan 并覆盖相关字段
- 要么：
  - 明确把返回值切换到“mutation result”语义，不再回传旧 plan 字段

当前这两种语义被混在一个 payload 里，状态不自洽。

### P2: `scheduled-prompts` 合同文档仍未写清“binding 必须先存在”

涉及文档：

- `docs/contracts/scheduled-prompts.zh-CN.md:27`
- `docs/contracts/scheduled-prompts.zh-CN.md:43`
- `docs/contracts/scheduled-prompts.md:30`
- `docs/contracts/scheduled-prompts.md:46`

现状：

- 代码层上，`binding/submit-prompt` 现在已明确 fail-close：
  - binding 不存在时返回 `prompt_denied_binding_not_found`
- 但合同文档当前只写了：
  - target binding 可以“当前还没绑定 thread”
- 没继续写清：
  - 这里说的是“已有 binding，但当前无 thread”
  - 不是“任意原始 `binding_id` 都会隐式创建 binding”

为什么这仍是问题：

- 这个仓库明确把合同文档当作长期维护的事实源之一
- 行为已经收紧，但合同没同步，后续很容易再次把“缺失 binding 时该 fail-close”改松
- 对 operator 来说，也会误解 `prompt send` 的前置条件

建议收敛方向：

- 在 `scheduled-prompts` 合同里明确补一句：
  - target binding 必须已经存在
  - 允许“binding 已存在但当前尚无 thread”
  - 不允许“缺失 binding 时隐式创建新 binding”

## 3. 已验证但未发现新问题的部分

本轮没有再发现下列路径上的新 correctness 回退：

- `default_thread_memory_mode` 的配置读取、模板暴露与基础 seed 注入
- `fcodex` / proxy 对已持久化 memory mode 的 resume 注入
- 前一轮 scheduled prompt 修复后的：
  - `binding not found` fail-close
  - `announce` 只在 `started=true` 后发出

## 4. 本地验证

解释器：

- `python`

已执行测试：

```bash
python -m pytest -q \
  tests/test_codex_app_server.py \
  tests/test_codex_handler.py \
  tests/test_feishu_codexctl.py \
  tests/test_install_templates.py \
  tests/test_runtime_admin_controller.py
```

结果：

- `418 passed`

另外做了两组最小人工复现：

1. `thread/memory` 在“当前 mode 已等于目标 mode”时，仍给出 reset 计划
2. `thread/memory` 在成功 reset+apply 后，返回结果仍保留旧的 `plan_status` / `reason_code`

两组都能稳定复现。

## 5. 建议优先级

建议处理顺序：

1. 先去掉 `profiles.<name>.memories` 这条与 upstream schema 不一致的 override 形状
2. 再修 thread-wise next-load 设置的 no-op 短路
3. 然后修 `thread/memory` 成功后的返回 payload 自洽性
4. 最后补齐 `scheduled-prompts` 合同文档

## 6. 建议补的回归测试

至少补下面几条：

1. `/memory` 在目标 mode 已等于当前持久化 mode 时，应直接成功，不得提供 reset
2. `/profile` 在目标 profile 已等于当前持久化 profile 时，应直接成功，不得提供 reset
3. `thread/memory --mode <same>` 应直接返回成功，不得要求 `--reset-backend`
4. `thread/memory` 成功应用后，返回的 `plan_status` / `reason_code` 不得继续保留旧计划状态
