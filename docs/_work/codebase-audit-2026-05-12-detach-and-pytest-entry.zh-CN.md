# `feishu-codex` 近期提交复核：事务收口、`binding clear-all` 回归、shell completion 与 pytest 入口

日期：2026-05-12

补充：第 3 节记录的是修复前复核时坐实的问题与证据；截至当前本地工作树，`3.2` 与 `3.3` 已按第 5 节修复。

## 1. 范围

本文不是重新做一轮全仓库泛审视，而是专门复核最近几次提交：

1. `a900937` `test: add pytest config and dev requirements`
2. `40331f5` `fix: harden binding detach and clear transactions`
3. `8f37eb1` `Avoid proxy lock files leaking into cwd`
4. `ff85fee` `Add zsh and PowerShell shell completion`
5. `d09d8fa` `Add bash completion for local CLIs`

本轮更新后的判断是：

1. 之前记录的 `detach` / `binding clear` 持久化失败事务缺口，已经被 `40331f5` 收口，不应继续写成“当前 HEAD 仍成立问题”。
2. `40331f5` 曾同时引入一条控制面回归：`binding clear-all` 在运行态视图与持久化 store 脱钩时，不再保证清空全部 bookmark；当前工作树已修复，见 `5.1`。
3. `a900937` 已经把 bare `pytest` 的入口问题收口；新环境测试入口现在有了明确最小路径。
4. `ff85fee` 暴露过一条 Windows 发布面问题：PowerShell completion 的安装与卸载路径不对称，可能留下 profile 残钩子；当前工作树已修复，见 `5.2`。
5. `8f37eb1` 对应的 `fcodex resume` reconnect 窗口，我这次没有稳定复现；它暂时仍应记为观察项，不是当前已坐实回归。
6. 当前全量 `pytest` 虽然已经稳定通过，但测试进程峰值 RSS 仍明显偏高；这更像测试基础设施问题，不是业务 correctness 回归。

结合当前产品面，主要用户路径仍然是：

- 普通用户安装、配置、启动 / 重启服务
- 必要时创建实例
- 日常主要使用 `fcodex`
- 偶尔用 `feishu-codexctl` 查询 thread，尤其是按 `thread-name` 全局定位
- 更偏运维 / 控制面的动作才会碰 `binding clear-all`、卸载、重新安装等路径

本文仍属于 `docs/_work/` 下的审视记录，不升级为正式合同或架构事实源。

## 2. 实际检查

### 2.1 当前测试基线

在仓库根目录执行：

```bash
pytest -q
python -m pytest -q
```

当前工作树上两者结果一致：

- `804 passed`
- `18 warnings`
- 无失败

warning 仍然主要来自第三方依赖的 deprecation warning，以及并发测试里 `fork()` 的提示，不是这几次提交新增的 correctness 失败。

### 2.2 `pytest` 入口复核

当前工作树已新增：

- [pyproject.toml](/home/zlong/llm/feishu-codex/pyproject.toml:38)
- [requirements-dev.txt](/home/zlong/llm/feishu-codex/requirements-dev.txt:1)

这两处作用要分开看：

1. bare `pytest` 现在可以直接工作，直接原因是 [pyproject.toml](/home/zlong/llm/feishu-codex/pyproject.toml:38) 里新增了：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

2. 新环境的最小测试依赖入口则是：

```bash
python -m pip install -r requirements-dev.txt
```

它解决的是“别人的环境 / 新切换环境如何把测试依赖装齐”，不是 bare `pytest` 能否导入仓库模块的直接原因。

因此，这条问题在当前 `HEAD` 上已经不应继续列为未解决问题。

### 2.3 旧事务缺口复核

`40331f5` 新增并通过了几组关键回归：

- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:238)
- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:266)
- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:495)
- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:590)
- [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:1201)

我也额外做了一个 smoke check：把 `ChatBindingStore.save(...)` 打桩成失败后再调用 `detach_binding_locked(...)`，当前结果是：

- 内存态仍保持 `attached`
- subscriber 仍在
- store 仍保持 `attached`

这说明此前“先改内存 / 先撤订阅，再落盘；落盘失败后留下半状态”的主问题，在当前 `HEAD` 上已经被收口。

### 2.4 修复前 `binding clear-all` 语义回归最小复现

相关位置：

- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:568)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494)
- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:365)

这一小节记录的是修复前最小复现，用来说明为什么后续需要 `84c9ebe`。当时服务启动时会先 `hydrate` 全量 stored bindings，所以这条回归**不是**每次干净启动都会立刻触发的问题；它更准确地说，是“当运行态 binding 视图和持久化 store 事实脱钩时，`clear-all` 不再具备最后兜底清场能力”。

我做的最小复现是：

1. 先构造一个当前 runtime 已加载的 live binding
2. 再向 `ChatBindingStore` 额外写入一个当前 runtime map 里不存在的 stale binding
3. 调用 `clear_all_bindings_for_control()`

修复前复现结果是：

- live binding 被清掉
- 返回结果看起来成功
- 但那个额外的 stale binding 仍然留在 store 里

同样的复现脚本在 `40331f5` 之前的 `ff85fee` 基线上不会残留，因为旧实现在清完运行态 bindings 后还会额外执行 `_clear_all_stored_bindings()`。当前 `HEAD` 已不再复现，见 `5.1`。

### 2.5 修复前 PowerShell completion 安装 / 卸载路径复核

相关位置：

- [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5)
- [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:410)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:433)

这一小节同样记录的是修复前复核结果，用来解释为什么后续需要 `84c9ebe`。当时安装逻辑会在 [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5) 里把 `FC_POWERSHELL_PROFILE_PATH` 设成**当前 host** 的 `$PROFILE.CurrentUserAllHosts`；但卸载时如果没有这个环境变量，则会回退到 [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115) 的默认路径。

我复现的结果是：

1. 安装阶段把 completion block 写进一个 profile 路径
2. 卸载阶段按默认回退路径执行移除
3. completion 脚本文件会被删掉
4. 但原 profile 文件里的 managed block 仍然残留

也就是说，这条问题的坏结果不是“completion 文件没删掉”，而是“profile 里的自动加载钩子没被删掉”。当前 `HEAD` 已按安装时记录的实际路径对称清理，见 `5.2`。

### 2.6 `fcodex resume` reconnect 观察

相关位置：

- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:1009)
- [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:2115)

我这次做了三层复核：

1. 全量 `python -m pytest -q`
2. 单独反复跑 `tests/test_codex_app_server.py -k resume_style_reconnect`
3. bare `pytest` 同样反复跑该单测

这次都没有复现失败，所以它目前更像：

- 一次曾观测到的时序型失败
- 当前尚未重新坐实的 flake / race 候选

更具体地说，这条问题打的不是“`thread/resume` 业务逻辑本身报错”，而是 proxy 生命周期上的一个时序窗口：

1. wrapper 先启动本地 cwd proxy [bot/fcodex.py](/home/zlong/llm/feishu-codex/bot/fcodex.py:743)
2. upstream 连接这个 proxy
3. 第一次连接意外断开
4. proxy 在没有活跃连接时启动 idle watchdog [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:1039)
5. 如果第二次连接还没来得及进入 handler、watchdog 就先执行了 `server.shutdown()`，就会在客户端看到 `ConnectionRefusedError` [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:1049)

也就是说，坏结果发生在 websocket 握手前，属于“监听已经关掉”，不是 resume payload 注入 profile / memory mode 的逻辑错误。

这里要把两个不同超时分开理解：

1. 当前这条观察真正相关的是 proxy idle window，默认值是 [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:58) 的 `30.0s`
2. [bot/fcodex.py](/home/zlong/llm/feishu-codex/bot/fcodex.py:720) 里还有一个 `5.0s` 的 proxy readiness timeout，但那是 wrapper 等待子进程打印 listen url 的启动超时，不是 `resume` 两次 websocket 连接之间的 grace window

如果真的撞上这条问题，用户侧坏结果会是：

1. 本地 `fcodex` wrapper 已经把 upstream Codex 指向本地 proxy URL
2. 但 upstream 第二次连回 `ws://127.0.0.1:<port>` 时，本地 proxy listener 已经关掉
3. 因此 `thread/resume` 请求根本还没发到后端 app-server
4. 用户看到的是 Codex TUI 没能正常进入，通常伴随一次本地 websocket connect failure / `ConnectionRefusedError`

### 2.7 `pytest` 高内存占用观察

我在当前工作树重新量了几次：

```bash
/usr/bin/time -v python -m pytest -q
```

当前结果：

- `804 passed, 18 warnings`
- 峰值 RSS 约 `11.46 GB`

再按测试文件拆分后：

1. 单独跑 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:1)，峰值 RSS 约 `1.70 GB`
2. 单独跑 [tests/test_codex_handler.py](/home/zlong/llm/feishu-codex/tests/test_codex_handler.py:1)，峰值 RSS 约 `210 MB`
3. 单独跑 [tests/test_manage_cli.py](/home/zlong/llm/feishu-codex/tests/test_manage_cli.py:1) + [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:1)，峰值 RSS 约 `181 MB`

继续把 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:1) 按测试类拆分后，最可疑的是 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:779) `CodexRpcClientTests`：

- 单独跑这 7 条测试，峰值 RSS 约 `604 MB`
- 其中只跑 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828) 这一条，峰值 RSS 约 `262 MB`
- 同组剩余 6 条合起来只有约 `44 MB`

这说明高内存并不是全仓库平均偏高，而是集中在一小组测试，且其中至少有一条测试非常可疑。

## 3. 发现

### 3.1 已收口：`detach` / `binding clear` 持久化失败事务缺口

这一条需要明确从“仍成立问题”改成“已收口”。

当前依据不是主观推断，而是三层证据一致：

1. `40331f5` 已把 `detach_binding_locked(...)`、`detach_thread_bindings_locked(...)`、`deactivate_binding_locked(...)`、`deactivate_bindings_locked(...)` 改成 staged-persist-then-commit 顺序，关键实现集中在 [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:417) 和 [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:551)。
2. 新回归测试已经覆盖了单 binding 与 batch 路径上的 `save()` / `clear()` 失败回滚。
3. 我补的 smoke check 也确认当前失败后不会再留下旧文档记录的那种半提交状态。

因此，旧文档里把这两条继续列为“当前 HEAD 仍成立 correctness 风险”的部分，应视为已被后续提交覆盖。

### 3.2 修复前中风险回归：`binding clear-all` 不再保证清空全部持久化 bookmark

相关位置：

- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:568)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494)

问题本质：

- 旧实现在清完当前 runtime bindings 后，还会执行一次 `_clear_all_stored_bindings()`。
- 当时实现改成只对 `binding_keys_locked()` 返回的运行态 bindings 做 `deactivate_bindings_locked(...)`。
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494) 的 `binding_keys_locked()` 只代表当前 runtime map，不代表持久化 store 的全量事实。

这意味着一旦 runtime 视图和 store 脱钩，`binding clear-all` 就不再符合它自己的命令合同：

- 合同写的是“清除当前实例下全部 binding bookmark”
- 当时实现变成了“清除当前 runtime 已知的 binding bookmark”

#### 3.2.1 会在什么场景触发

这条不是普通 happy path 上必现的问题；它会在“store 里有当前 runtime map 看不到的 bookmark”时触发。

更现实的触发来源包括：

1. 服务启动后，运维或其他工具直接修改了 `chat_bindings.json`
2. 之前的异常 / 手工修复过程留下了运行态未加载的残留 bookmark
3. 未来如果再出现任何 runtime/store 事实脱钩，这个 `clear-all` 将不再是可靠兜底手段

因为 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:365) 启动时会 hydrate 全量 store，所以这条风险主要打在**恢复、修复、清场**场景，而不是普通新装后的第一条命令。

#### 3.2.2 用户使用路径

直接用户路径就是：

1. 本地执行 `feishu-codexctl binding clear-all`

这条路径对普通用户不常见，但对运维 / 控制面是实打实的恢复入口，因为它本来就承担“把当前实例 bookmark 清干净”的职责。

#### 3.2.3 用户会看到什么

如果问题触发，用户会看到一种很危险的“假成功”：

1. `clear-all` 返回成功
2. 当前 runtime 里看得见的 binding 的确被清掉
3. 但 store 里仍残留一部分 bookmark
4. 后续如果这些残留再次被加载，用户会发现“明明 clear-all 过了，为什么还有旧 binding 又回来”

这条问题比直接抛错更差，因为它会让控制面清场动作失去可信度。

#### 3.2.4 修复前缺的回归

当时新增回归主要覆盖了“batch clear 失败时是否回滚”，例如：

- [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:1201)

但没有覆盖：

- `clear-all` 在 runtime/store 事实不一致时，是否仍能清空持久化全量 bookmark
- “有 live binding + 有 store-only stale binding” 这类恢复场景

#### 3.2.5 当时建议修法

建议二选一，不要停在当前中间态：

1. 保留现在的 batch deactivate 事务实现，但在成功提交后恢复 `_clear_all_stored_bindings()` 这一步，继续保证命令合同是“清 store 全量”。
2. 或者显式把 `clear-all` 重写成以 store 为主视角的清场逻辑，而不是只迭代 runtime map。

如果不做这一步，这个命令就不再是可靠的最终修复入口。

### 3.3 修复前中风险发布面问题：PowerShell completion 卸载会留下 profile 残钩子

相关位置：

- [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5)
- [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:410)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:433)

问题本质：

- 安装时使用的是“当前 host 实际 profile 路径”
- 卸载时在没有环境变量帮助的情况下，使用的是“代码默认推导的 profile 路径”
- 这两个路径并不保证相同

所以当时卸载不是严格对称的 install/uninstall 对。

#### 3.3.1 会在什么场景触发

更现实的触发路径是：

1. Windows 用户先用 `install.ps1` 安装
2. 安装时 completion block 被写进某个具体 host 的 `CurrentUserAllHosts` profile
3. 之后用户从另一个 PowerShell host，或没有保留同一环境变量上下文的卸载路径执行 `feishu-codex uninstall`

#### 3.3.2 用户使用路径

直接用户路径：

1. Windows 上运行 `./install.ps1`
2. 之后运行 `feishu-codex uninstall`

这不影响 Linux / macOS 主路径，但它确实影响 Windows 发布面的一致性。

#### 3.3.3 用户会看到什么

如果问题触发，用户通常会看到：

1. 卸载命令看起来成功
2. completion 脚本文件本身已经被删掉
3. 但旧 profile 里仍保留自动加载 block
4. 之后每次开 PowerShell，仍可能继续尝试 source 一个已不存在的脚本

这会形成典型的“卸载不干净”。

#### 3.3.4 修复前缺的回归

当时测试主要覆盖了“同一组环境变量上下文下安装再卸载”的 happy path，例如：

- [tests/test_manage_cli.py](/home/zlong/llm/feishu-codex/tests/test_manage_cli.py:1009)

但没有覆盖：

- 安装阶段与卸载阶段使用不同 PowerShell profile 路径
- `install.ps1` 注入过 `FC_POWERSHELL_PROFILE_PATH`，卸载阶段没有该环境变量时是否仍能清理干净

#### 3.3.5 当时建议修法

建议至少做一条：

1. 安装时把实际写入的 profile 路径持久化下来，卸载时按同一路径删除
2. 或者卸载时同时尝试清理几类常见 PowerShell profile 路径
3. 并补一条“安装 host 与卸载 host 不一致”的回归测试

### 3.4 已收口：开发测试入口对 bare `pytest` 的不自洽

这条在当前 `HEAD` 上已经解决。

当前更准确的开发测试最小路径是：

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

这条路径不会要求开发者执行 `pip install .` 或 `pip install -e .`，也不会引入额外 `console_scripts` 污染当前 Python / Conda 环境，符合仓库当前的本地安装纪律。

### 3.5 补充观察：`fcodex resume` 的 reconnect 窗口仍值得继续盯住

相关位置：

- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:1049)
- [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:2115)

当前判断：

1. 这次没有稳定复现失败
2. 全量 pytest 与多次单测复跑都通过
3. 因此它不应和上面两条已坐实问题放在同一级别

但因为这条路径直接落在本地继续既有 live thread 的主路径上，如果后续在慢机器、CI、WSL、或高系统负载下再次出现，就应优先升级成正式缺陷。

更具体的场景判断是：

1. 用户本地执行 `fcodex resume <thread_id|thread_name>`
2. proxy 已经启动，但 upstream 连接尚未完全稳定
3. 第一次连接意外断开后，需要在短时间内完成第二次 reconnect
4. 本地资源吃紧、线程调度抖动、或 websocket accept 变慢时，第二次连接更可能撞上 idle shutdown 窗口

因此，这条不是“用户平时随便用就大概率炸”的问题，但在**正常用户路径 + 本地资源明显吃紧**时，风险确实会抬高，坏结果就是用户看到 `fcodex` 没能正常进入。

从修法上看，当前“第一次连接断开后，短时间内还能接受第二次连接”只是缓解，不是原理性消除。更稳的方向是把 startup reconnect grace 做成显式状态，而不是继续依赖通用 idle timeout：

1. proxy 首次接受连接后，如果该连接在启动期断开，进入单独的 reconnect grace 状态
2. 这段 grace 不应和普通 idle timeout 共用同一个截止时间
3. 只有 grace 用完、且 parent 仍无有效会话时，才允许真正 shutdown listener

### 3.6 测试基础设施问题：`CodexRpcClientTests` 很可能在制造高内存假象

相关位置：

- [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828)
- [bot/codex_protocol/client.py](/home/zlong/llm/feishu-codex/bot/codex_protocol/client.py:224)
- [bot/codex_protocol/client.py](/home/zlong/llm/feishu-codex/bot/codex_protocol/client.py:418)

当前最可疑的原因是：

1. 该测试直接把 `subprocess.Popen` patch 成默认 `MagicMock`
2. 生产代码会立刻启动两条 daemon 线程去读 `stdout` / `stderr`
3. `_log_stream(...)` 的退出条件是 `readline()` 返回空串
4. 但 `MagicMock.stdout.readline()` / `MagicMock.stderr.readline()` 不会自然返回 `""`

这会让日志线程持续存活，随后又叠加全量测试后部两组 `fork` 并发测试的地址空间放大 warning：

- [tests/test_instance_registry_store.py](/home/zlong/llm/feishu-codex/tests/test_instance_registry_store.py:95)
- [tests/test_thread_runtime_lease_store.py](/home/zlong/llm/feishu-codex/tests/test_thread_runtime_lease_store.py:253)

如果按这个方向修测试，原则上不需要牺牲原有测试能力：

1. 对 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828) 而言，它真正想看护的是“默认 `codex` 命令不可用时，是否退回稳定启动命令，并拼出正确 argv”，不是日志线程是否无限读取 `MagicMock`
2. 因此更合理的修法是把 `Popen` double 收紧成会自然 EOF 的假流，或直接 stub 掉日志线程启动；断言仍旧落在启动命令、listen URL、以及 managed start 合同上
3. 对后面的并发 store 测试而言，它真正想看护的是跨进程并发正确性，不是 Linux `fork` 继承多线程父进程地址空间这一副作用
4. 所以这部分修复目标应是“收紧测试替身与进程模型，让测试只覆盖自己宣称的合同”，而不是“删掉高成本测试换轻量 smoke test”

因此，我当前更倾向于把这条判断为：

- 测试桩 / 测试线程生命周期问题
- 会严重干扰本地全量 pytest 的资源占用判断
- 但不应直接解读成产品运行时的内存泄漏

这条问题的修法可以保持原测试能力，不需要削弱 coverage：

1. 对 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828) 这类只关心 `Popen` argv 的测试，改用显式 `_Proc` stub，并让 `stdout = StringIO(\"\")`、`stderr = StringIO(\"\")`
2. 或者在该类测试里直接把 `bot.codex_protocol.client.threading.Thread` patch 成 stub，避免日志线程真实启动
3. 如果修完这组 mock 后全量峰值仍高，再考虑把后面两组并发测试从 `fork` 切到 `spawn` / `forkserver`

这些改法都不会改变原来要看护的合同：

- managed app-server 的启动命令是否正确
- fallback listen url / runtime store 记录是否正确
- 跨进程并发 register / acquire 是否仍能保全所有条目

## 4. 一句话结论

截至 2026-05-12 当前工作树，我对这几次近期提交的更新判断是：

1. `detach` / `binding clear` 的持久化失败事务缺口已经被 `40331f5` 收口。
2. `pytest` 入口不一致问题已经被 `a900937` 收口。
3. 本文复核时坐实过的两条开放问题，当前工作树都已修复：
   - `binding clear-all` 重新保证清空当前实例下全部持久化 bookmark
   - PowerShell completion 安装 / 卸载重新回到同一路径事实源
4. `fcodex resume` reconnect 目前继续记为观察项，不升格为已坐实回归。
5. `pytest` 高内存问题在当前工作树已明显收口；它最终被证实主要是测试基础设施问题，不是这几次提交引入的新产品回归。

## 5. 修复落地

### 5.1 `binding clear-all` 已恢复按持久化事实清场

当前工作树里，[bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550) 在执行 `clear-all` 前，会先通过 [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:382) 把 store-only bindings 补 hydrate 到运行态，再沿用现有 batch deactivate 事务路径统一清除。

新增回归覆盖：

- [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:1239) 补了“1 个 live binding + 1 个 store-only stale binding”的恢复场景
- 结果要求是 `clear_all_bindings_for_control()` 返回成功后，runtime 与 `chat_bindings.json` 都必须为空

这意味着合同里的“清除当前实例下全部 binding bookmark”已经重新和实现对齐。

### 5.2 PowerShell completion 安装 / 卸载已恢复路径对称

当前工作树里，[bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:137) 会把安装时实际写入的 PowerShell completion script / profile 路径持久化到配置根目录；卸载时优先按这份记录清除，而不是只依赖调用当下的 `FC_POWERSHELL_PROFILE_PATH`。

新增回归覆盖：

- [tests/test_manage_cli.py](/home/zlong/llm/feishu-codex/tests/test_manage_cli.py:1067) 补了“安装阶段有 `FC_POWERSHELL_PROFILE_PATH`，卸载阶段没有该环境变量提示”的路径
- 结果要求是 profile managed block、completion script、路径元数据都要被清干净

这条发布面问题当前也不再成立。

### 5.3 2026-05-12 当前复核结果

我对本轮修复后的判断是：

1. `84c9ebe fix: restore clear-all and shell completion cleanup` 已经把此前 `3.2`、`3.3` 两条问题实质收口
2. 我没有在这次修复里看到新的 correctness 回归
3. 相关新增回归测试通过：
   - `python -m pytest -q tests/test_runtime_admin_controller.py -k clear_all_bindings_for_control`
   - `python -m pytest -q tests/test_manage_cli.py -k shell_completion`
4. 当前全量基线也已通过：

```bash
python -m pytest -q
```

结果是：

- `804 passed`
- `10 warnings`

### 5.4 当前仍建议单独立项的一件事

1. 把 `fcodex resume` startup reconnect 窗口改成显式 grace-state，而不是继续依赖普通 idle timeout

### 5.5 `pytest` 高内存问题已明显收口

当前工作树里，这条问题已经按上面的方向完成了实际修复：

1. [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828) 不再让默认 `MagicMock` 驱动真实日志线程，而是改成显式 EOF 的 `Popen` stub + no-op 线程替身
2. [tests/test_instance_registry_store.py](/home/zlong/llm/feishu-codex/tests/test_instance_registry_store.py:100) 与 [tests/test_thread_runtime_lease_store.py](/home/zlong/llm/feishu-codex/tests/test_thread_runtime_lease_store.py:258) 的并发进程测试不再从多线程父进程里继续 `fork`，而是改成 `spawn`

我在当前工作树重新测得：

1. 单独跑 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:828) 该可疑测试，峰值 RSS 约 `46 MB`
2. 单独跑 [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:1)，峰值 RSS 约 `46 MB`
3. 全量 `python -m pytest -q` 结果为 `804 passed, 10 warnings`，峰值 RSS 约 `220 MB`

这说明此前的高内存主因确实在测试替身与测试进程模型，而不是产品运行时 correctness 或内存泄漏。
