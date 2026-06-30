# `focus` / `fcodex` Shared Backend 运行时模型

英文原文：`docs/architecture/focus-shared-backend-runtime.md`

本文是 FOCUS 当前 shared-backend / wrapper 运行时模型的实现说明。
如果你想知道 `focus` / `fcodex`、shared backend、动态端口、cwd 代理这些机制为什么存在，应优先看本文。

本文解释下列能力背后的实现模型：

- `focus --cd` / `fcodex --cd`
- 本地 websocket 代理
- FOCUS 使用的 shared Codex remote app-server

另见：

- `docs/contracts/thread-profile-semantics.zh-CN.md`
- `docs/decisions/shared-backend-resume-safety.zh-CN.md`
- `docs/architecture/focus-design.zh-CN.md`

## 1. 上游基线

- 上游项目：[`openai/codex`](https://github.com/openai/codex.git)
- 当前本地验证基线：`codex-cli 0.118.0`，本地可解析到上游 tag
  `rust-v0.118.0`（commit
  `b630ce9a4e754d35a1f33e4366ba638d18626142`），核对日期为 2026-04-03
- 如果本文后续需要引用具体上游源码位置，应优先使用绑定到该基线
  commit 的 `openai/codex` permalink，而不是开发者本机 checkout 路径
- 本文描述的是当前 FOCUS 基于 stock Codex CLI / `codex app-server` / `--remote` 行为验证出的运行时模型；如果上游版本后续调整 remote 协议或 app-server 行为，本文也应随之更新。

## 2. 运行时组成

在稳定状态下，本地 / 共享路径如下：

```text
shared CODEX_HOME
machine-global coordination (`FOCUS_GLOBAL_DATA_DIR`)
  - instance registry
  - thread runtime lease

instance A / default
  Feishu client
    -> FOCUS service
       -> instance-local shared codex app-server
          （默认优先 ws://127.0.0.1:8765；冲突时自动切到空闲本地端口）

focus / fcodex shell wrapper
  -> select target instance backend
  -> local owner-filtering proxy
     -> selected instance-local shared codex app-server
        -> upstream Codex TUI
```

关键点在于：

- `shared backend` 现在指的是**实例内共享 backend**
- 多个实例共享的是 `CODEX_HOME`，不是同一个 live app-server backend
- managed backend 启动会经过机器级协调；即使多个实例在同一条命令里几乎同时启动，也必须各自落到独立的 live backend URL，而不能误连到别的实例已经占住的 `8765`
- 飞书和 `focus` / `fcodex` 如果要安全继续同一个 live thread，预期应连接到同一个**实例 backend**
- 实例内 shared app-server 的 websocket 面现在默认要求 capability token；token 放在该实例 `FOCUS_DATA_DIR` 下的私有文件里，由 service / `focusctl` / `focus` / `fcodex` 作为 backend client 读取并通过 `Authorization: Bearer ...` 发送
- `focus` / `fcodex` 本地代理的 websocket 面使用**独立的**一次性 bearer token；该 token 只通过父子进程环境变量传递，不复用 service token，也不出现在命令行参数里

## 3. 为什么需要 `focus` / `fcodex`

裸 `codex` 通常自己管理 backend 生命周期。对于普通本地使用这没有问题，但当你希望飞书与本地 TUI 操作同一个 live thread 时，这不是合适的默认行为。

`focus` / `fcodex` 存在的目的，是提供：

- 与所选飞书实例共享的单一 backend
- `resume <thread_name>` 这类 wrapper 级名字解析
- 一个用于修正 remote 模式工作目录行为的兼容层

## 4. 安装后的 Wrapper 环境

多实例下，要区分三层本地路径：

1. 共享的 `CODEX_HOME`
2. 每实例独立的 `FOCUS_CONFIG_DIR` / `FOCUS_DATA_DIR`
3. 机器级共享协调目录 `FOCUS_GLOBAL_DATA_DIR`

其中：

- `default` 实例保持与原单实例安装路径兼容
- 命名实例落在 `instances/<name>` 子目录下
- `FOCUS_GLOBAL_DATA_DIR` 默认落在数据根目录下的 `_global/`

安装后的 `focus` / `fcodex` wrapper 会先做基础环境准备，再把控制权交给 Python wrapper。
这一层会：

1. 如果存在，则加载机器级配置根目录下共享的 `focus.env`
2. 准备默认实例的 `FOCUS_CONFIG_DIR` / `FOCUS_DATA_DIR` 根信息
3. 再由 Python wrapper 解析 `--instance`、实例注册表、runtime lease，为本次启动选出目标实例

从代码职责看，这条启动链路也被有意拆成两段：

- wrapper 负责选定目标实例，以及 backend 连接前的本地环境准备
- proxy 只负责传输层修补

因此，“wrapper 与 service 共享的本地状态”应理解为：

- **同一实例**共享自己的配置目录与 runtime backend 发现状态
- wrapper 与 daemon 都会加载同一个机器级 `focus.env` provider 环境文件
- **所有实例**共享 `CODEX_HOME`
- **所有实例**共享机器级实例注册表与 thread runtime lease

当默认 `ws://127.0.0.1:8765` 被占用、某实例服务自动切到其它空闲端口时，
`focus` / `fcodex` 会通过该实例的数据目录里记录的运行时发现状态找到当前实际 backend 地址。

## 5. `--cd` 的真实工作方式

`focus` / `fcodex` 每次启动时会解析出一个最终生效的工作目录：

- 如果用户传了 `--cd` 或 `-C`，就用它
- 否则使用当前 shell cwd
- 如果用户显式传了 `--cd` / `-C` 但缺少值，wrapper 应直接报错，而不是静默回退到当前 cwd

然后它会对这个值做两件彼此独立的事：

1. 把 `--cd` 继续透传给 upstream `codex`
2. 把同一个 cwd 传给本地代理

这种“双重处理”是有意为之。

## 6. 为什么需要本地代理

最初的问题是：

- 在 remote 模式下，upstream Codex TUI 不一定会稳定地在 `thread/start` 上发送 `cwd`
- shared app-server 于是会回退到它自己进程的工作目录
- 对 FOCUS 而言，这个回退目录通常是 `~/.local/share/focus`

结果就是：

- 直接运行 `focus` / `fcodex` 新开线程时，工作目录可能会错误落到 service data 目录，而不是调用者当前 shell 所在目录

本地代理正是为了解决这个非常具体的缺口：

- 它把 websocket 流量转发到 shared backend
- 当它看到 `thread/start` 且 `params.cwd` 缺失或为空时，会注入 wrapper 选定的最终 cwd
- 其它流量原样透传
- 它自己的升级握手必须先通过本地 bearer token 鉴权，然后才允许接入 backend

这样可以把补丁面控制得非常窄。

## 7. 为什么代理生命周期跟随父进程

排查中我们确认，upstream 的 remote resume 并不是单连接流程。

`codex --remote ... resume <id>` 可能会：

1. 先连接一次，用于会话查找或启动准备
2. 断开
3. 再次连接，进入真正的 TUI 会话

因此，代理不能在第一个 websocket client 断开后就安全退出。

当前模型：

- 当由 `focus` / `fcodex` 启动时，代理会拿到 wrapper 进程 PID
- 代理会一直存活，直到这个父进程退出
- 在测试中如果没有父 PID，它仍可退化为短空闲超时模式

这就是当前实现能稳住 resume 期间重连的原因。

## 8. 哪些路径使用 Shared Backend

默认情况下，下列入口都走 shared backend：

- 飞书命令
- 直接运行 `focus` 或 `fcodex`
- `focus <prompt>`
- `fcodex <prompt>`
- `focus resume <thread_id>`
- `fcodex resume <thread_id>`
- `focus resume <thread_name>` 在 wrapper 侧解析完成之后
- `fcodex resume <thread_name>` 在 wrapper 侧解析完成之后

这里的“shared backend”都指所选实例 backend。
当前 shell 层已不再提供 `focus /threads` / `fcodex /threads` 这类 wrapper slash 自命令；本地线程发现改由 `focusctl thread list` 负责。

## 9. 显式 `--remote` 是特例

如果用户显式给 `focus` / `fcodex` 传了 `--remote`，wrapper 就不会再强行走 shared-backend 路径。

这意味着：

- 不会插入本地 cwd 修正代理
- 不再隐含 shared-backend 保证
- 用户是在明确选择一个自定义 remote 目标

这是有意设计的。显式 `--remote` 的语义就是“使用我指定的目标”。

## 10. 与裸 `codex` 的区别

相较于裸 Codex TUI，`focus` / `fcodex` 增加了这些语义：

- 默认与所选飞书实例共享 backend
- 对 `resume`，支持在所选 shared backend 上做 thread-name 解析
- 通过一个轻量本地代理修补 cwd
- 对 shared-backend 路径上的 websocket 面做本地鉴权收口：backend 与 proxy 各自持有独立 token，且都不再复用 service token
- proxy 只负责传输层修补；它不再综合或持久化任何项目自管的 thread 级设置合同
- 本地控制面 websocket 不应被用户的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`
  劫持：Python 侧连接 shared backend 时显式禁用 websocket proxy；wrapper 启动上游
  Codex TUI 时只补强 `NO_PROXY/no_proxy` 的 loopback 项，不删除用户外网代理环境变量

其中职责边界是显式的：

- wrapper：在透传前只保留一层很窄的本地 CLI 语义。它会消费 `--instance`，拦截
  `focus --help` / `fcodex --help` 与 `focus resume --help` / `fcodex resume --help` 这类 wrapper 自有帮助，并拒绝已经删除的
  shell-only slash 入口；除此之外，仍把上游原生参数（包括 `-p/--profile`）原样透传
- proxy：只在 websocket 传输边界做 cwd 修补与 owner 过滤，不再承担 thread 级设置注入

但一旦进入运行中的 TUI，命令语义就回到 upstream Codex 的默认行为。

## 11. 已知注意事项

### Upstream remote 协议未来可能变化

cwd 代理之所以存在，是因为当前 upstream remote 模式的行为如此。如果 upstream 后续修改了：

- `thread/start` 的 payload 形状
- remote 会话启动顺序
- 重连时机

wrapper 可能需要跟着调整。相关上游实现与变更历史，应以 [`openai/codex`](https://github.com/openai/codex.git) 为准。

### 裸 `codex` 仍不在共享线程契约内

如果用户在飞书或 `focus` / `fcodex` 正在写某个线程时，又用裸 `codex` 配合它自己的 backend 打开同一个线程，FOCUS 无法把这件事变安全。

### TUI 内的发现逻辑仍是 upstream 的

在 TUI 里，`/resume` 的 picker 行为仍然由 upstream 决定，它可能不同于：

- 飞书 `/threads`
- `focusctl thread list`
- `focus resume <thread_name>` / `fcodex resume <thread_name>`

### Shared backend 可用性是前提

如果所选实例的 shared app-server 没有运行，或者不可达，`focus` / `fcodex` 就无法完成它的职责。这时启动会快速失败，而不是悄悄退回一个隔离的本地 backend。

## 12. 开发者入口

相关实现文件：

- wrapper 参数处理与 shared-backend 启动：
  - `bot/fcodex.py`
- 代理传输与 cwd 注入：
  - `bot/fcodex_proxy.py`
- 飞书侧 adapter / handler：
  - `bot/codex_handler.py`
  - `bot/adapters/codex_app_server.py`
- shared discovery 逻辑：
  - `bot/thread_resolution.py`
