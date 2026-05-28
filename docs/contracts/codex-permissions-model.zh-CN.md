# Codex 权限模型

英文原文：`docs/contracts/codex-permissions-model.md`

本文记录 `feishu-codex` 当前暴露的 `approval_policy` 与 `permissions_profile_id`，以及 upstream 里 legacy `sandbox` / canonical `permissions` 的关系。

写这篇文档有两个目的：

- 让飞书侧文案始终与 upstream Codex 行为保持一致
- 把精简用户帮助与实现细节、排障细节分开

上游基线：

- Codex 源码仓库：[`openai/codex`](https://github.com/openai/codex.git)
- 当前本地验证基线：`codex-cli 0.118.0`，本地可解析到上游 tag
  `rust-v0.118.0`（commit
  `b630ce9a4e754d35a1f33e4366ba638d18626142`），核对日期为 2026-04-03
- 文中后续的上游文件 / 行号引用，均固定到这次基线对应的 commit，便于后续开发者恢复当时讨论的精确源码快照

## 1. 三层概念

`feishu-codex` 当前暴露两个正式 runtime setting，并需要理解一个上游 legacy 概念：

1. `approval_policy`
- 运行在什么时机需要停下来等待审批

2. `permissions_profile_id`
- 当前飞书 binding 在下一轮注入哪个 upstream permission profile id

3. legacy `sandbox`
- 上游仍兼容，但飞书侧不再把它当成正式 persisted setting

重要点在于：飞书侧当前的 `/permissions` 已不再是“组合预设”，而是独立设置 upstream canonical `permissions` profile id。

## 2. Approval 与 Sandbox

最简洁的心智模型是：

- `sandbox` 是技术执行边界
- `approval_policy` 是审批边界

这个模型总体是对的，但还需要几处精度修正。

### 2.1 在 upstream 里，approval 不必然等于“人工审批”

upstream Codex 把 approval 建模为“策略 + reviewer 流程”，并不严格等同于“必须由一个人点击批准”。

不过在本仓库当前产品合同里，默认 reviewer 仍然是飞书用户，因此把 `approval_policy` 解释为审批边界，对当前产品语义仍然是准确的。

相关上游参考：

- [`codex-rs/protocol/src/protocol.rs:L627`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/protocol/src/protocol.rs#L627)
- [`codex.yaml.example:35`](../../config/codex.yaml.example)

### 2.2 Sandbox 不是“换了一套工具”

切换 `sandbox` 的核心含义，不是换掉可用工具列表。
更准确地说，它改变的是同一批 shell 命令和工具在执行时要套上的约束。

例如：

- `read-only` 不等于“只剩读命令可用”
- `workspace-write` 不等于“换了一套 shell”
- `danger-full-access` 不等于“突然多出额外工具”

更准确的表述是：

- 模型会收到不同的权限上下文
- 运行时会对命令执行施加不同的 OS 级限制

这就是为什么 sandbox 改变时，用户体感上有时像是“换了工具”，但底层核心工具面其实没有变。

## 3. Upstream Approval 语义

当前 upstream `AskForApproval` 包括：

- `untrusted`
  - 只有“已知安全且只读文件”的命令会被自动批准
- `on-request`
  - 由模型决定什么时候请求审批
- `never`
  - 从不请求审批；失败会直接返回
- `on-failure`
  - upstream 已弃用

本仓库已不再在用户可选的飞书表面暴露 `on-failure`。若旧本地配置里仍写了它，
配置层会自动按 `on-request` 归一化处理。

相关上游参考：

- [`codex-rs/protocol/src/protocol.rs:L627`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/protocol/src/protocol.rs#L627)
- [`codex-rs/core/src/codex.rs:L1648`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/core/src/codex.rs#L1648)

应避免的写法：

- “untrusted 表示只允许读命令”
- “never 表示命令完全不受限制”

这些说法不对，因为 approval policy 讨论的是升级与审批流程，而不是完整的运行时限制模型。

## 4. Upstream Sandbox 语义

upstream 对平台沙箱的选择是明确的：

- macOS：Seatbelt
- Linux：Linux sandbox helper，默认走 bubblewrap
- Windows：restricted-token sandbox，并提供 elevated pipeline

相关上游参考：

- [`codex-rs/sandboxing/src/manager.rs:L49`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/sandboxing/src/manager.rs#L49)
- [`codex-rs/linux-sandbox/src/lib.rs:L1`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/linux-sandbox/src/lib.rs#L1)
- [`codex-rs/core/src/seatbelt.rs:L1`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/core/src/seatbelt.rs#L1)
- [`codex-rs/features/src/lib.rs:L110`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/features/src/lib.rs#L110)
- [`codex-rs/windows-sandbox-rs/src/elevated/command_runner_win.rs:L1`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/windows-sandbox-rs/src/elevated/command_runner_win.rs#L1)
- [`codex-rs/windows-sandbox-rs/src/token.rs:L308`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/windows-sandbox-rs/src/token.rs#L308)

这也是为什么 Docker 只能算一个很松的类比。
Codex 的主路径并不是切到一份单独 image 或替换 rootfs，而是使用宿主机原生的进程级沙箱机制。

### 4.1 Linux

Linux helper 在代码里直接写明：

- 进程内限制：`no_new_privs` 与 `seccomp`
- 文件系统隔离：bubblewrap

因此，更贴切的理解是“宿主机上的轻量进程沙箱”，而不是“把任务丢进一个完整容器镜像”。

### 4.2 macOS

macOS 路径会生成 Seatbelt policy，并把命令放在 Seatbelt 入口下执行。

### 4.3 Windows

Windows 路径使用 restricted token。除此之外，upstream 还实现了一条带专用 runner 的 elevated sandbox pipeline。

所以“restricted token / elevated runner”不是拍脑袋类比，而是有源码对应的上游实现点。

## 5. Writable Roots 与受保护路径

`workspace-write` 不应该被过度简化为“可以写当前工作目录”。

更准确的说法是：

- 写入允许发生在配置好的 writable roots 内
- 这些可写根下的一些顶层受保护路径，默认仍保持只读

upstream 当前至少会保护：

- `.git`
- `.agents`
- `.codex`

相关上游参考：

- [`codex-rs/protocol/src/permissions.rs:L1098`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/protocol/src/permissions.rs#L1098)

这个区别很重要，因为它解释了为什么 agent 通常可以修改项目文件，但仍然会被拦在 repo 元数据或 Codex 元数据之外。

## 6. 为什么沙箱有时“看起来像坏了”

Sandbox 相关失败，大致分成两类，而且含义完全不同：

1. 沙箱工作正常，并正确拦截了写入、网络访问或受保护路径
2. 沙箱后端自身在 bootstrap 阶段就失败了

第二类情况下，即便是无害的只读命令，也可能在真正执行目标命令之前就失败。

这时用户很容易误以为：

- 读权限配置错了
- 工具本身没了
- Codex 换了一套命令面

但真正的问题通常出在更前面的 sandbox setup。

在验证本仓库时，本机就复现了这类错误：

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

这也说明，排障指导应该进入正式文档，而不是只存在于口口相传的经验里。

## 7. 排障参考

upstream CLI 提供了明确的 sandbox 调试子命令：

- `codex sandbox linux`
- `codex sandbox macos`
- `codex sandbox windows`

相关上游参考：

- [`codex-rs/cli/src/main.rs:L252`](https://github.com/openai/codex/blob/b630ce9a4e754d35a1f33e4366ba638d18626142/codex-rs/cli/src/main.rs#L252)

建议的排障顺序：

1. 先区分这是策略拦截，还是 sandbox bootstrap 失败
2. 确认当前平台理论上应走哪条 backend
3. 直接测试对应平台的 sandbox 子命令
4. 如果外层 VM / container 已提供隔离，再判断内层 Codex sandbox 是否仍有价值，还是只是在与宿主环境冲突

## 8. 推荐产品文案

对 `feishu-codex` 这类面向用户的文档，最稳妥的写法是：

- `sandbox` 控制技术执行边界
- `approval_policy` 控制什么时候必须先审批才能继续
- `/permissions` 设置独立的 upstream canonical `permissions` profile id
- `/approval` 单独设置审批策略
- 飞书侧不再暴露 `/sandbox` 用户面

推荐的简明表述：

- “`/permissions` 决定后续 turn 采用哪条权限基线。”
- “`/approval` 决定什么时候必须先停下来等待审批。”
- “权限基线决定执行边界；审批策略决定是否需要停下来等待批准。”

不要在顶层 README 里过度承诺那些未来可能变化的实现细节。
像平台后端、实现路径、排障分层这类内容，更适合放在像本文这样的专门文档里。
