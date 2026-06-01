# Managed Backend Startup Profile 决策

英文原文：`docs/decisions/managed-backend-startup-profile.md`

另见：

- `docs/contracts/thread-profile-semantics.zh-CN.md`
- `docs/contracts/thread-memory-semantics.zh-CN.md`
- `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`
- `docs/architecture/fcodex-shared-backend-runtime.zh-CN.md`
- `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

## 1. 状态

本文记录当前已经对齐的产品结论与后续推荐方向。

它区分两层内容：

- **当前已验证事实**
  - 现有代码与上游行为已经如此
- **后续推荐能力**
  - 还未在本仓库实现，但这是当前更合适的产品路线

在实现真正落地之前，当前正式行为仍以现有 contracts 与代码为准。

## 2. 问题

当前项目存在一个很具体的 provider / catalog 张力：

- 裸 `codex -p <profile>` 每次通常都有自己独立的 app-server / TUI 运行时
- `feishu-codex` 一个实例则长期复用同一个 shared backend

这会导致一个核心差异：

- 裸 `codex` 可以在启动时按该次 profile 解析自己的 backend-global model metadata / catalog
- `feishu-codex` 的 shared backend 则只能在 backend 启动时确定一套 backend-global model metadata / catalog

因此，如果某个 provider 例如 ZAI / GLM 需要自己的 `model_catalog_json` 才能获得更准确的模型元数据、context windows 与相关行为调优，那么：

- 裸 `codex` 可以通过独立启动路径吃到这套 catalog
- `feishu-codex` 的 shared backend 若没有在启动时就吃到这套 catalog，后续 thread-wise `/profile` 只能改 thread 的 `profile / model / model_provider`，不能把 backend-global catalog 一起切掉

典型症状是：

- 实际 provider 调用也许已经是 GLM
- 但 backend 对该模型的 metadata 仍未命中
- TUI / `/model` / 基础提示会退回 fallback metadata
- 进而出现 warning，或出现偏 GPT / OpenAI 的自我识别与默认行为

## 3. 当前事实

### 3.1 backend-global catalog 与 thread-wise profile 不是一层状态

本项目当前已经明确区分：

- `profile`
- `memory`

它们属于 **thread-wise next-load state**。

也就是说，它们承诺的是：

- 对受支持的恢复路径，同一个 thread 从 unloaded 恢复为 loaded 时，应复用同一份持久化 next-load 设置

但 backend-global model metadata / `model/list` / catalog 路径不是这层状态的一部分。

它们属于 backend 启动时就已决定的共享事实。

### 3.2 `remote` 模式只是“连接外部 backend”

`app_server_mode = remote` 的准确含义是：

- 当前实例不再自己拉起并拥有 backend 进程
- 它只连接一个外部已存在的 app-server endpoint

因此 remote 模式可以被拿来“接入一个别处已按特定 profile 启动好的 backend”，但这仍然只是连接外部 backend，而不是让本实例自己具备 provider-aware 的 backend 启动控制能力。

### 3.3 `remote` 模式不适合作为 thread-wise next-load 设置的主路径

当前仓库里，正式保留的设置面已经收敛为：

- 实例 startup profile
- binding-wise next-turn settings

这两类设置在目标 thread 仍 loaded 时，经常需要通过 unload / `reset-backend` 路径收敛。

但 remote 模式下，本实例不拥有 backend 进程，因此不能执行 `reset-backend`。

这意味着 remote 不是一个只影响 catalog 的小差异，而是会连带削弱：

- `/profile`
- 以及依赖 `reset-backend` 收敛的本地 control-plane 路径

### 3.4 当前项目故意不保留“实例级默认 profile”

当前合同已经明确：

- 项目不再保留“实例级默认 profile”这一层用户概念

这里的关键不是“现有 thread 会不会被立刻追改”，而是更深一层的用户心智问题：

- 一旦某个能力被叫做“默认 profile”，用户会自然推断：
  - 只要 thread 没有显式指定 profile
  - 它每次重新 load 时就会按这个默认 profile 重新解析

这与当前 thread-wise next-load 合同冲突。

本项目当前的事实源仍然是：

- 对 unloaded thread，持久化 thread-wise next-load state 才是事实源

## 4. 已放弃的路线

### 4.1 不再追求“同一个 backend 同时让 GPT / GLM 都吃到各自最优 catalog”

这是当前明确放弃的目标。

原因不是实现细节难，而是状态层本身不匹配：

- catalog / model metadata 是 backend-global
- `profile` / `memory` 是 thread-wise

只靠 thread-wise profile 切换，无法让一个长期存活的 shared backend 同时按 thread 拥有两套不同的 backend-global catalog 真相。

### 4.2 不把 `remote` 作为 ZAI catalog 的主解决方案

`remote` 可以是调试或临时接线路径，但不应成为本项目用好 ZAI 的主要产品路线。

原因：

- 它把 provider-aware backend 启动控制移到了仓库外
- 它让当前实例失去 `reset-backend`
- 它会连带影响 thread-wise `profile` / `memory` 的正式收敛路径

### 4.3 不把新能力命名成“实例级默认 profile”

如果后续真的加入新的 backend 启动能力，它不应叫：

- `default_profile`
- `instance_default_profile`

因为这些名字会把 backend 启动默认值误说成 thread-wise next-load 事实源。

## 5. 决策

### 5.1 后续更合适的路线是 `managed backend startup profile`

如果后续要让某个实例更好地服务特定 provider，例如 ZAI / GLM，那么更合适的能力是：

- `managed backend startup profile`

它的目标不是替代 thread-wise profile，而是补上一层当前缺失的 backend 启动控制。

### 5.2 这项能力的准确语义

这项能力若实现，语义应收紧为：

- 仅在 `app_server_mode = managed` 时生效
- 只影响当前实例自己拉起的 backend
- 在 backend 启动与 backend reset 后重启时使用
- 决定 backend 启动时吃哪套活动配置
- 从而影响 backend-global 的：
  - 活动 profile 解析
  - `model/list`
  - model metadata
  - catalog 路径

它**不应**承担以下语义：

- 不写入 thread-wise profile store
- 不引入新的项目自管 thread 级持久化设置
- 不追改已 loaded thread
- 不把自己伪装成 thread 的“默认 profile 真相”

### 5.3 它与现有 thread-wise 状态的关系

若这项能力落地，推荐关系应是：

- backend startup profile
  - 只定义 backend-global 启动默认值
- thread-wise profile / memory
  - 继续定义某个 thread 下次恢复时应使用的持久化 next-load 设置

也就是说：

- 现有 thread 的真相仍由 thread-wise persisted state 决定
- backend startup profile 只是 backend 启动时的共享基线

对于新线程，只有在**没有显式 thread-wise 种子、也没有请求级显式覆盖**时，backend startup profile 才会以 backend 默认值的形式间接发挥作用。

### 5.4 它不是“按 provider 路由到不同 backend”

当前产品方向不接受：

- 在同一个实例里按 thread/profile/provider 动态选择不同 backend

因此 backend startup profile 的设计前提是：

- 一个实例仍只拥有一个 managed backend
- 只是这个 backend 的启动配置可以按实例角色更明确地选定

## 6. 配套约束

### 6.1 若使用 startup profile，实例级 `model` / `model_provider` 应尽量保持空

当前新线程创建路径会优先把请求级 / 实例级的 `model`、`model_provider` 注入到 `thread/start`。

如果后续引入 startup profile，但实例配置里仍写死：

- `model`
- `model_provider`

那么这些显式注入值仍可能掩盖 backend 启动默认值，让语义重新变模糊。

因此，若目标是让 shared backend 在多个 thread-wise profile 间工作，同时保留更清楚的 backend 启动基线，实例级 `model` / `model_provider` 应优先保持空。

### 6.2 `/reset-backend` 应沿用同一份 startup profile

若后续实现这项能力，则 `reset-backend` 后重启 managed backend 时，也应沿用同一份 startup profile。

否则用户会看到一种不一致：

- 实例首次启动时是 ZAI-aware backend
- `reset-backend` 后又退回普通 backend

这会直接破坏该能力的可预期性。

## 7. 操作层结论

在当前这轮讨论对齐后，仓库应采用以下结论：

- 不再追求“同一个 backend 混用 GPT / GLM，且两边同时吃到各自最优 catalog”
- 若要把 ZAI 用好，同时保留现有 `/profile`、`/reset-backend` 与 turn-time 设置这套产品面合同，更合适的未来路线是：
  - 一个独立实例
  - `managed` backend
  - backend 启动时显式吃到 ZAI 所需 catalog 的 startup profile
- 这项能力应被定义成 backend 启动控制，而不是 thread 的默认 profile 事实源

## 8. 非目标

本文不定义以下能力：

- 同一个 backend 内的 provider-specific catalog overlay
- 按 thread/profile/provider 动态路由到不同 backend
- 对当前 shipped 合同中 thread-wise profile / memory 语义的改写
- 对 remote 模式增加“伪 reset-backend”一类的补丁语义
