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

### 2.4 `binding clear-all` 语义回归最小复现

相关位置：

- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:568)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494)
- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:365)

当前服务启动时会先 `hydrate` 全量 stored bindings，所以这条回归**不是**每次干净启动都会立刻触发的问题；它更准确地说，是“当运行态 binding 视图和持久化 store 事实脱钩时，`clear-all` 不再具备最后兜底清场能力”。

我做的最小复现是：

1. 先构造一个当前 runtime 已加载的 live binding
2. 再向 `ChatBindingStore` 额外写入一个当前 runtime map 里不存在的 stale binding
3. 调用 `clear_all_bindings_for_control()`

当前 `HEAD` 的结果是：

- live binding 被清掉
- 返回结果看起来成功
- 但那个额外的 stale binding 仍然留在 store 里

同样的复现脚本在 `40331f5` 之前的 `ff85fee` 基线上不会残留，因为旧实现在清完运行态 bindings 后还会额外执行 `_clear_all_stored_bindings()`。

### 2.5 PowerShell completion 安装 / 卸载路径复核

相关位置：

- [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5)
- [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:410)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:433)

当前安装逻辑会在 [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5) 里把 `FC_POWERSHELL_PROFILE_PATH` 设成**当前 host** 的 `$PROFILE.CurrentUserAllHosts`；但卸载时如果没有这个环境变量，则会回退到 [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115) 的默认路径。

我复现的结果是：

1. 安装阶段把 completion block 写进一个 profile 路径
2. 卸载阶段按默认回退路径执行移除
3. completion 脚本文件会被删掉
4. 但原 profile 文件里的 managed block 仍然残留

也就是说，这条问题的坏结果不是“completion 文件没删掉”，而是“profile 里的自动加载钩子没被删掉”。

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

## 3. 发现

### 3.1 已收口：`detach` / `binding clear` 持久化失败事务缺口

这一条需要明确从“仍成立问题”改成“已收口”。

当前依据不是主观推断，而是三层证据一致：

1. `40331f5` 已把 `detach_binding_locked(...)`、`detach_thread_bindings_locked(...)`、`deactivate_binding_locked(...)`、`deactivate_bindings_locked(...)` 改成 staged-persist-then-commit 顺序，关键实现集中在 [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:417) 和 [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:551)。
2. 新回归测试已经覆盖了单 binding 与 batch 路径上的 `save()` / `clear()` 失败回滚。
3. 我补的 smoke check 也确认当前失败后不会再留下旧文档记录的那种半提交状态。

因此，旧文档里把这两条继续列为“当前 HEAD 仍成立 correctness 风险”的部分，应视为已被后续提交覆盖。

### 3.2 中风险回归：`binding clear-all` 不再保证清空全部持久化 bookmark

相关位置：

- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:568)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494)

问题本质：

- 旧实现在清完当前 runtime bindings 后，还会执行一次 `_clear_all_stored_bindings()`。
- 当前实现改成只对 `binding_keys_locked()` 返回的运行态 bindings 做 `deactivate_bindings_locked(...)`。
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:494) 的 `binding_keys_locked()` 只代表当前 runtime map，不代表持久化 store 的全量事实。

这意味着一旦 runtime 视图和 store 脱钩，`binding clear-all` 就不再符合它自己的命令合同：

- 合同写的是“清除当前实例下全部 binding bookmark”
- 当前实现变成了“清除当前 runtime 已知的 binding bookmark”

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

#### 3.2.4 当前缺的回归

当前新增回归主要覆盖了“batch clear 失败时是否回滚”，例如：

- [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:1201)

但没有覆盖：

- `clear-all` 在 runtime/store 事实不一致时，是否仍能清空持久化全量 bookmark
- “有 live binding + 有 store-only stale binding” 这类恢复场景

#### 3.2.5 建议修法

建议二选一，不要停在当前中间态：

1. 保留现在的 batch deactivate 事务实现，但在成功提交后恢复 `_clear_all_stored_bindings()` 这一步，继续保证命令合同是“清 store 全量”。
2. 或者显式把 `clear-all` 重写成以 store 为主视角的清场逻辑，而不是只迭代 runtime map。

如果不做这一步，这个命令就不再是可靠的最终修复入口。

### 3.3 中风险发布面问题：PowerShell completion 卸载会留下 profile 残钩子

相关位置：

- [install.ps1](/home/zlong/llm/feishu-codex/install.ps1:5)
- [bot/platform_paths.py](/home/zlong/llm/feishu-codex/bot/platform_paths.py:115)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:410)
- [bot/shell_completion.py](/home/zlong/llm/feishu-codex/bot/shell_completion.py:433)

问题本质：

- 安装时使用的是“当前 host 实际 profile 路径”
- 卸载时在没有环境变量帮助的情况下，使用的是“代码默认推导的 profile 路径”
- 这两个路径并不保证相同

所以当前卸载不是严格对称的 install/uninstall 对。

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

#### 3.3.4 当前缺的回归

当前测试主要覆盖了“同一组环境变量上下文下安装再卸载”的 happy path，例如：

- [tests/test_manage_cli.py](/home/zlong/llm/feishu-codex/tests/test_manage_cli.py:1009)

但没有覆盖：

- 安装阶段与卸载阶段使用不同 PowerShell profile 路径
- `install.ps1` 注入过 `FC_POWERSHELL_PROFILE_PATH`，卸载阶段没有该环境变量时是否仍能清理干净

#### 3.3.5 建议修法

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

## 4. 一句话结论

截至 2026-05-12 当前工作树，我对这几次近期提交的更新判断是：

1. `detach` / `binding clear` 的持久化失败事务缺口已经被 `40331f5` 收口。
2. `pytest` 入口不一致问题已经被 `a900937` 收口。
3. 本文复核时坐实过的两条开放问题，当前工作树都已修复：
   - `binding clear-all` 重新保证清空当前实例下全部持久化 bookmark
   - PowerShell completion 安装 / 卸载重新回到同一路径事实源
4. `fcodex resume` reconnect 目前继续记为观察项，不升格为已坐实回归。

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
