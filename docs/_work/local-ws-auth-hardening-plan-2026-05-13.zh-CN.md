# 本地 WebSocket 鉴权收口计划 — 2026-05-13

Status: working material under `docs/_work/`. Not a repository fact.

本文记录本轮关于“多本机账户场景下，`feishu-codex` / `fcodex` 本地 websocket 暴露面”的调查结论与执行计划。

当前目标不是立刻重写 transport 体系，而是先把已经对齐的安全结论、边界与实施顺序固定下来，供后续实现直接使用。

## 1. 背景

当前机器上可能存在多个 Unix 账户，它们各自运行 `feishu-codex`。

用户的真实目标是：

- 通过“多账户”获得一定程度的信息安全隔离
- 避免 A 账户仅凭本机 localhost 访问能力，就连接到 B 账户正在运行的 `codex app-server`
- 避免 A 账户在 B 账户打开 `fcodex` TUI 期间，趁本地 proxy 存活而接入它的 live thread

因此，本轮讨论的核心不是“外网安全”，而是：

- **同一台机器上的不同账户之间**
- **能否靠当前本地监听模型完成隔离**

结论是：**当前不能。**

## 2. 已确认的事实

### 2.1 飞书入站不是本地公开监听面

`feishu-codex` 与飞书之间当前使用的是：

- 由本地服务主动建立到飞书的长连接 websocket
- 使用 `app_id` / `app_secret` 完成飞书侧认证

因此：

- 这不是一个“本地开端口等飞书推消息”的模型
- 本机其他账户或外部网络不能直接把请求打到这条本地飞书入站链路上

### 2.2 本地 control-plane 已有鉴权，但不是本轮主问题

`feishu-codex` 还会启动一个本地 control-plane endpoint，供：

- `focusctl`
- 多实例管理
- service admin 动作

当前它监听 `tcp://127.0.0.1:<port>`，但请求必须带 `auth_token`，服务端也会校验。

因此：

- 它虽然是 localhost 监听
- 但它不是当前最主要的安全缺口

### 2.3 当前真正危险的是 upstream `codex app-server` 的 loopback websocket

当前 `feishu-codex` 管理的 backend 默认是：

- `ws://127.0.0.1:8765`
- 若冲突则自动切到空闲本地端口

并且当前实现里：

- service 连接 app-server 时不带 `Authorization`
- `focusctl` 远程连 app-server 时不带 `Authorization`
- `fcodex` 本地 proxy 连接 backend 时不带 `Authorization`

而 upstream 当前对 loopback websocket 的默认行为是：

- 如果没有显式配置 `--ws-auth ...`
- websocket upgrade 直接放行

因此：

- 本机其他账户只要知道或扫到端口
- 就能直接连接该 app-server
- 并发 JSON-RPC 请求

这不是“只能继续聊天”的能力，而是可能直接调用：

- `thread/read`
- `thread/list`
- `fs/readFile`
- `process/spawn`
- `thread/shellCommand`

也就是说，A 账户确实可能借 B 账户的 app-server 权限读取线程、读文件、起进程、执行命令。

### 2.4 `fcodex` 打开时的本地 proxy 是第二个危险面

`fcodex` 当前并不是让 upstream TUI 直接连 shared backend。

它会先启动一个本地 websocket proxy，再让 upstream `codex --remote ws://127.0.0.1:<port>` 连这个 proxy。

当前这层 proxy：

- 监听 `ws://127.0.0.1:<ephemeral-port>`
- 没有额外鉴权

因此：

- 只要某个 `fcodex` 会话还活着
- 本机其他账户理论上也能连接这个 proxy
- 进而蹭进当前 live backend thread 会话

所以，若只给 service backend 加 auth，而不处理 proxy，本轮问题并没有真正解决。

## 3. 已对齐的结论

### 3.1 当前不做 `unix://` 迁移，先做纯 websocket 收口

虽然上游对 `unix://` 的本地 control socket 支持较强，但本项目当前大量路径都把 backend 视为 `ws://...`：

- 默认值
- runtime discovery
- 动态端口回退
- `fcodex` wrapper
- 测试基线

因此，当前阶段的首选不是“backend 改成 unix socket”，而是：

- **继续使用 websocket**
- **把 websocket auth 做完整**

### 3.2 不做“双模式长期并存”

当前不建议把正式运行路径做成：

- backend 一会儿 `unix://`
- 一会儿 `ws:// + auth`
- 由配置自由切换

原因：

- 会让配置、运行时发现、故障排查、测试矩阵都分叉
- 不符合当前仓库“收敛到一条清晰路径”的方向

因此，本轮对齐的方向是：

- **选一条主路径**
- **先补安全洞**
- **避免长期双轨维护**

### 3.3 纯 websocket 方案必须做“整条链路收口”

这次已经明确，不存在“只给 service app-server 加 auth 就算完成”的版本。

正式目标必须同时覆盖两条 websocket 链路：

1. `feishu-codex` / `focusctl` / `fcodex proxy` -> managed `codex app-server`
2. upstream `codex` TUI -> `fcodex` local proxy

否则：

- 第一条补了，第二条还漏
- 多账户本地隔离依然不成立

### 3.4 control-plane 维持现状，不混入本轮抽象

当前 service control-plane 已自带 `auth_token`。

因此本轮不应把“local websocket hardening”与“control-plane 重做”混在一起。

本轮只处理：

- app-server websocket
- local proxy websocket

不处理：

- 飞书连接层
- control-plane 协议重写

### 3.5 目标是“跨账户本地隔离增强”，不是“同账户进程隔离”

这次安全目标需要说清楚。

做完之后，我们预期能防的是：

- **另一 Unix 账户**
- 仅凭 localhost 可达性
- 直接接入本账户运行中的 app-server / proxy

它不能防的是：

- 同一账户下的恶意进程
- root
- 操作系统级别的越权

## 4. 推荐方案

### 4.1 总体方向

本轮正式建议为：

- **采用纯 websocket 路线**
- **service backend 使用 upstream 已支持的 websocket capability token**
- **`fcodex` local proxy 也增加独立 websocket 鉴权**

换言之：

- 不改 transport 族谱
- 只补 auth

### 4.2 backend 侧：使用 upstream `--ws-auth capability-token`

上游已正式支持：

- `--ws-auth capability-token`
- `--ws-token-file /absolute/path`

因此本项目建议：

- managed `codex app-server` 启动时总是带上 capability-token auth
- 由本项目自己准备 token file
- 所有合法客户端在 websocket 握手时都发送 `Authorization: Bearer <token>`

当前不建议首选 signed JWT bearer token，原因是：

- capability token 更简单
- 已足够满足本地 loopback 鉴权需求
- 不需要再引入额外签名材料与时钟语义

### 4.3 proxy 侧：新增本项目自己的 loopback websocket auth

`fcodex` local proxy 不是 upstream server；它是本项目自己的 websocket server。

因此这里不能依赖 upstream `--ws-auth ...`，需要本项目自己实现：

- proxy 启动时生成一份临时高熵 token
- proxy websocket upgrade 前校验 `Authorization: Bearer <token>`
- 未携带 / 错 token 直接拒绝

并且：

- `fcodex` wrapper 启动 upstream TUI 时，自动注入 `--remote-auth-token-env <ENV_NAME>`
- 同时在该子进程环境里写入对应 token

这样 upstream `codex --remote` 会在连接 proxy 时自动带 bearer token。

### 4.4 两类 token 分开

本轮建议显式区分两类 token：

1. `backend websocket auth token`
   - 作用对象：managed `codex app-server`
   - 生命周期：实例级、可持久化
   - 使用方：
     - `feishu-codex` service
     - `focusctl`
     - `fcodex proxy`

2. `local proxy auth token`
   - 作用对象：单次 `fcodex` 启动出来的本地 proxy
   - 生命周期：进程级、临时
   - 使用方：
     - 当前这次 upstream `codex` TUI

不要把它们混成一个抽象，原因是：

- 责任边界不同
- 生命周期不同
- 泄露后的影响面也不同

## 5. 不选的方向

### 5.1 当前不做 backend `unix://` 迁移

不是因为它不好，而是因为：

- 当前仓库对 `ws://...` 假设过深
- 改造面显著大于本轮需要
- 即使 backend 改成 `unix://`，`fcodex` proxy 这一层仍需要 websocket 安全面

因此它不适合作为本轮第一阶段。

### 5.2 当前不做“backend 支持 unix / ws 双模式切换”

理由同上：

- 维护成本高
- 排障认知负担高
- 与当前收敛方向不一致

### 5.3 当前不把 proxy 也改成 `unix://`

当前 upstream TUI 的 `--remote` 只接受：

- `ws://host:port`
- `wss://host:port`

因此 `fcodex` local proxy 当前不适合作为 `unix://` 暴露给 upstream TUI。

## 6. 实施计划

### Phase 1: 固化 backend websocket auth

目标：

- 所有 managed `codex app-server` 均启用 capability-token auth

建议步骤：

1. 新增实例级 backend websocket token 存储
   - 0600 文件
   - 路径归属当前实例数据目录或配置目录
2. `CodexRpcClient` 启动 managed app-server 时追加：
   - `--ws-auth capability-token`
   - `--ws-token-file <path>`
3. `CodexRpcClient` 连接 backend 时，在 websocket 握手中带：
   - `Authorization: Bearer <token>`
4. `focusctl` 远程 adapter 也走同一 token 读取与握手逻辑
5. `fcodex proxy -> backend` 这条链路也改为带 backend bearer token

完成标准：

- 未带 token 的本地 websocket 连接无法接入 managed app-server
- service / codexctl / proxy 这三条合法链路保持可用

### Phase 2: 固化 `fcodex` local proxy websocket auth

目标：

- 本地其他账户不能趁 proxy 存活时接入当前 `fcodex` 会话

建议步骤：

1. proxy 启动时生成临时高熵 token
2. proxy websocket server 在 upgrade 前校验 bearer token
3. `fcodex` wrapper 为本次启动：
   - 选择一个内部 env var 名
   - 写入 proxy token
   - 透传 `--remote-auth-token-env <name>` 给 upstream `codex`
4. 保持显式 `--remote` 语义不变
   - 只有 wrapper 自己生成的 local proxy 路径才自动注入这套 auth

完成标准：

- 无 token 连接 local proxy 会失败
- 当前 `fcodex` 正常启动 / resume / 重连不回归

### Phase 3: 测试与回归封口

建议最少覆盖：

1. `CodexRpcClient`
   - 启动参数包含 `--ws-auth capability-token --ws-token-file ...`
   - websocket client 握手包含 `Authorization`
2. `focusctl`
   - remote adapter 能读取并携带 token
3. `fcodex proxy`
   - 未授权连接被拒
   - 合法 bearer token 连接成功
4. `fcodex wrapper`
   - 自动注入 `--remote-auth-token-env`
   - 环境变量正确下发到 upstream `codex`
5. 全量测试

## 7. 预期效果

完成以上两阶段后，预期效果是：

- 本机其他账户无法仅凭 localhost 端口扫描接入某实例的 managed app-server
- 本机其他账户无法在 `fcodex` 会话存活期间直接接入其 local proxy
- 飞书侧与本地 shared-backend 路径保持原有产品形态
- 不需要在当前阶段引入 `unix://` 与双模式配置复杂度

这会把当前“loopback 可达即默认可信”的状态，收紧为：

- **只有持有对应 token 的合法本地客户端，才能接入 websocket runtime**

## 8. 后续文档动作

本文件当前只是执行前工作材料。

实现完成后，建议再做两步：

1. 把最终事实补入正式架构文档
   - `docs/architecture/fcodex-shared-backend-runtime.zh-CN.md`
   - `docs/architecture/feishu-codex-design.zh-CN.md`
2. 若行为面形成稳定合同，再视需要补一份正式 decision / contract
   - 说明为什么当前选择“pure websocket + end-to-end auth”
   - 明确它解决的威胁模型与不解决的范围

## 9. 2026-05-14 对 `dev` 实现的补充审视

下面这些不是“计划方向”，而是基于当前 `dev` 分支实际实现的补充审视结论，
供后续收尾时直接参考。

### 9.1 当前 `dev` 相比早期 worktree 版本更好的点

1. `bot/local_websocket_auth.py` 已把本地 websocket 鉴权相关的 token store、
   bearer header 构造、header 解析与环境变量名统一收口。
   - 这比把 app-server token helper 单独散在别的模块里更清晰。
2. `fcodex` wrapper 已不再把 proxy auth token 和 service token 通过 argv 传给
   `bot.fcodex_proxy`。
   - 当前做法是：
     - proxy auth token 通过 `FOCUS_REMOTE_AUTH_TOKEN`
     - service token 通过 `FOCUS_SERVICE_TOKEN`
   - 这比早期实现把 `--service-token` 暴露在进程参数里更稳。
3. `CodexRpcClient` 现在接收的是 `app_server_data_dir`，再由
   `AppServerWebsocketAuthTokenStore` 负责 `ensure()/require()`。
   - 这比在各层显式传 token file path 更内聚，也更不容易漏掉路径归属。

### 9.2 我认为应继续改进的地方

1. 把 proxy -> backend 的 token 读取改成 fail-close。
   - 当前 `bot/fcodex_proxy.py` 的 `_load_backend_auth_headers(...)` 使用的是
     `AppServerWebsocketAuthTokenStore(...).load()`。
   - 结果是：
     - token 文件缺失时，不会立刻报错；
     - 而是返回空 header，再继续尝试与 backend 建立 websocket。
   - 这不符合本仓库当前偏好的 fail-close 路线。
   - 建议改成：
     - token 不存在 / 为空 / 读失败时，proxy 直接启动失败；
     - 错误信息应明确提示“目标实例尚未生成 backend websocket token，需确认升级并重启”。

2. 去掉 auth secret 查找里的 `"."` 回退。
   - 当前 proxy 侧 backend auth 读取仍允许：
     - `data_dir`
     - `FOCUS_DATA_DIR`
     - 最后回退到 `"."`
   - 对普通路径这也许只是“宽松”，但对安全敏感的 token 查找，这会把“配置错误”
     变成“在错误目录里静默找不到 token，再进入降级路径”。
   - 建议改成：
     - backend websocket auth 路径必须能确定实例 data dir；
     - 若 `data_dir` 和 `FOCUS_DATA_DIR` 都缺失，则直接报错，不允许 `"."` fallback。

3. 为上述 fail-close 语义补专门回归测试。
   - 目前测试已覆盖“合法 bearer token 工作”和“未授权 proxy client 被拒绝”，
     但还缺一条更关键的安全回归：
     - backend token 文件缺失时，proxy 应拒绝启动，而不是继续尝试无鉴权连接。
   - 建议补最少两条：
     - token 文件缺失 -> `run_proxy(...)` 启动失败
     - `data_dir` 缺失且 `FOCUS_DATA_DIR` 为空 -> 直接报错

### 9.3 我认为当前 `dev` 里最像真实 bug 的点

#### Bug A：backend token 缺失时，proxy 可能静默退化为“不带 Authorization 的连接尝试”

影响面：

- 文件：`bot/fcodex_proxy.py`
- 位置：`_load_backend_auth_headers(...)`

问题本质：

- 当前逻辑把“backend websocket token 丢失 / 未生成 / 读失败”处理成了“返回空 header”；
- 后续 `_handler(...)` 仍会继续 `connect(backend_url, ...)`。

为什么这算 bug，而不只是“错误提示不够好”：

1. 它违背当前项目已经明确对齐的 fail-close 目标。
2. 它会把本应在 proxy 启动阶段暴露的配置错误，延后成 backend 连接阶段的间接故障。
3. 如果未来出现混合版本、旧 backend、错误实例路由，或某些非预期兼容行为，
   这种“空 header 继续试”会把安全边界变模糊。

建议修法：

- 让 proxy 在拿不到 backend token 时立即失败；
- 不允许进入“不带 Authorization 也试一下”的分支。

#### Bug B：auth secret 查找允许 `"."` fallback，容易把实例目录配置错误掩盖掉

影响面：

- 文件：`bot/fcodex_proxy.py`
- 位置：backend auth header 构造所依赖的 data dir 解析

问题本质：

- 这条路径当前仍保留了对当前工作目录的隐式回退；
- 对 thread/profile/memory 之类普通状态，这种回退最多是错目录；
- 对 websocket auth token，这会把“实例上下文丢失”掩盖成“只是没读到 token”。

为什么值得当成 bug 看：

- 本项目之前已经吃过一次“路径默认值落到 cwd”的架构债；
- 安全敏感路径如果继续保留这类 fallback，后续很容易再演变成难定位问题。

建议修法：

- 对 backend auth token lookup，要求实例 data dir 是显式可确定的；
- 缺失就报错，不允许 cwd fallback。

### 9.4 2026-05-14 二次复核补记

在 `222226e Fail closed on missing backend ws auth` 之后，再次复核 `dev`，
前面 9.2 / 9.3 记录的两条主问题已经被修掉：

- proxy -> backend 改为 `require()`，缺 token 直接 fail-close
- backend auth data dir 不再允许 `"."` fallback
- 对应回归测试也已补齐

当时只剩一个仍需收尾的 active follow-up：Follow-up A。
该项已在本次实现里同步收口；Follow-up B 仅作为历史补记保留，不再属于当前待办。

#### Follow-up A（本次已收口）：remote backend 缺 token 时，客户端仍会白等完整个 connect timeout

影响面：

- 文件：`bot/codex_protocol/client.py`
- 位置：`_connect_ws_locked()` 与 `_websocket_auth_headers_for_connect()`

问题本质：

- remote 模式下，`_websocket_auth_headers_for_connect()` 会通过
  `AppServerWebsocketAuthTokenStore.require()` 读取 token；
- 但这个异常被 `_connect_ws_locked()` 的通用重试循环吞掉了；
- 因此当 token 文件缺失时，行为不是“立刻 fail-close”，而是一直重试到
  `connect_timeout_seconds` 用尽后才报错。

为什么值得修：

- 这不是瞬时网络问题，而是确定性的本地状态错误；
- 当前默认超时是 15 秒，用户会感知到无意义等待；
- 从语义上看，也不符合本轮“缺 auth 必须立即失败”的收口方向。

本次做法：

- 为 backend websocket auth token 缺失引入专用异常；
- 让 `_connect_ws_locked()` 对这类本地确定性错误直接抛出，不再进入通用重试分支；
- 补回归测试，验证缺 token 时不会继续 sleep / retry，也不会发起 websocket connect。

#### Follow-up B（历史补记，已收口）：`fcodex_proxy` 的 `--service-token` argv 入口已删除

影响面：

- 文件：`bot/fcodex_proxy.py`
- 位置：CLI 参数面与 `service_token` 读取逻辑

历史核对结果：

- 这不是本轮 websocket auth 加固新加的入口；
- 它最早来自 `d727e41 feat: add multi-instance runtime coordination`；
- 在那时，`fcodex` 确实会通过 argv 把 `--service-token` 传给 proxy；
- 到 `73fbff6 Harden local websocket auth surfaces`，实际调用链已经改成：
  - `proxy auth token` 走环境变量
  - `service token` 也走环境变量
- 但 `fcodex_proxy` 自己的 parser 仍保留了 `--service-token` 这个旧入口。

这条问题已收口：

- `fcodex_proxy` 不再接受 `--service-token`
- 统一只读取 `FOCUS_SERVICE_TOKEN`

为什么当时值得修：

- 当前正式调用链已经不需要它；
- 它会给后续内部调用、手工调试、甚至错误复制粘贴留下“secret 重新回到 argv”
  的后门；
- 从当前仓库偏好的“单一路径收口”看，保留这个入口没有明显增量价值。

最终做法：

- 删除 `--service-token` parser 参数；
- 统一只接受 `FOCUS_SERVICE_TOKEN` 环境变量。
