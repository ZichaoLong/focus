# `feishu-codex` detach / clear 事务缺口、`fcodex resume` 重连观察与 pytest 入口收口记录

日期：2026-05-12

## 1. 范围

本文记录本轮全面审视后，我对当前工作树的更新判断：

1. `detach` 路径在持久化失败时仍会留下部分提交状态。
2. `binding clear` / `archive` 路径在 bookmark 清理失败时也会留下部分提交状态。
3. `pytest` 入口不一致问题已在当前工作树收口，不再应继续列为“仍成立问题”。
4. 本地 `fcodex resume` 的 resume-style reconnect 路径，曾观测到一次时序型失败；当前更像潜在 flake / race，值得单独记。

从主要用户路径看：

- 第 1、2 条会直接打到飞书管理动作与 `feishu-codexctl` 控制面。
- 第 4 条会打到本地继续既有 live thread 的主路径。

普通操作者主要会：

- 安装、配置、启动 / 重启服务
- 必要时创建实例
- 日常主要使用 `fcodex`
- 偶尔使用 `feishu-codexctl` 查询 thread，尤其是按 `thread-name` 全局定位

本文不把这些内容升级成正式仓库事实源；它们当前仍属于 `docs/_work/` 下的审视记录。

## 2. 实际检查

### 2.1 测试基线

在仓库根目录执行：

```bash
pytest -q
python -m pytest -q
```

结果一致：

- `797 passed`
- 无失败
- 仅有第三方依赖 deprecation warning 与 `fork()` 相关测试告警

### 2.2 `pytest` 入口复核

当前工作树已新增：

- [pyproject.toml](/home/zlong/llm/feishu-codex/pyproject.toml:38)
- [requirements-dev.txt](/home/zlong/llm/feishu-codex/requirements-dev.txt:1)

这两处带来的变化，应该分开理解：

1. bare `pytest` 现在之所以能直接工作，根因是 [pyproject.toml](/home/zlong/llm/feishu-codex/pyproject.toml:38) 里新增了：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

其中：

- `pythonpath = ["."]` 负责把 repo root 加进 pytest 进程的导入路径，因此不再需要手工写 `PYTHONPATH=.`。
- `testpaths = ["tests"]` 只是把默认发现范围收口到 `tests/`。

2. [requirements-dev.txt](/home/zlong/llm/feishu-codex/requirements-dev.txt:1) 提供的是新环境的最小测试依赖入口：

```bash
python -m pip install -r requirements-dev.txt
```

它解决的是“如何装测试依赖”，不是 bare `pytest` 导入行为的直接原因，也不会产生 `pip install .` 那类 `console_scripts` 污染。

因此，这条问题在**当前工作树**上已经不再成立。

### 2.3 `detach` 路径最小复现

我直接构造了一个 `attached` 的 binding，然后把 `ChatBindingStore.save(...)` 打桩成抛错，再调用：

- `BindingRuntimeManager.detach_binding_locked(...)`
- `BindingRuntimeManager.detach_thread_bindings_locked(...)`

实际结果一致：

- 内存态 `feishu_runtime_state` 已变成 `detached`
- `attached_bindings_for_thread_locked(...)` 已为空
- interaction owner 已被释放
- 但落盘后的 `chat_bindings.json` 仍然保留 `attached`

也就是说，失败结果不是“完全没生效”，而是明确的**部分提交**。

### 2.4 `clear` / `archive` 路径最小复现

我另外直接构造了一个 `attached` 的 binding，然后把 `ChatBindingStore.clear(...)`
打桩成抛错，再调用：

- `BindingRuntimeManager.deactivate_binding_locked(...)`

实际结果是：

- 内存态里的 binding 已经从 `_runtime_state_by_binding` 被移除
- `bound_bindings_for_thread_locked(...)` 已经看不到它
- 但 `thread_subscribers(...)` 里仍然还挂着这个 binding
- interaction owner 也仍然保留
- 落盘后的 `chat_bindings.json` 仍然保留原 bookmark

也就是说，这条失败路径留下的不是“完全没生效”，而是另一种明确的**部分提交**：

- 内存态像“已清掉”
- 订阅态和 lease 态像“还没清掉”
- 落盘态也像“还没清掉”

这足以确认 `deactivate_binding_locked(...)` 自身存在事务缺口；而
`clear_binding_for_control(...)`、`clear_all_bindings_for_control(...)`、
`archive_thread_for_control(...)` 都会继承这条缺口。尤其是
`archive_thread_for_control(...)` 里，远端 `_archive_thread(...)` 还发生在
binding 清理之前，因此失败后的外部可见分裂会更严重。

### 2.5 `fcodex resume` 重连窗口观察

在本轮较早一次测试中，我执行过：

```bash
PYTHONPATH=. pytest -q
```

当时唯一失败的是：

```text
tests/test_codex_app_server.py::FCodexTests::test_proxy_stays_alive_across_resume_style_reconnect
```

对应测试场景：

- 第一次 websocket 连接向 proxy 发送 `thread/start`
- 连接关闭
- 短暂等待
- 第二次 websocket 连接向同一 proxy 发送 `thread/resume`

对应代码与测试：

- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:1009)
- [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py:2115)

当次失败表现为第二次连接拿到 `ConnectionRefusedError`。

但在当前工作树上，后续复跑：

- `pytest -q`
- `python -m pytest -q`

都已通过 `797` 个测试，因此我不把它升级成“当前稳定复现的问题”，而把它记成：

- **一次已观测到的 resume-style reconnect 时序型失败**
- 当前更像 flake / race 候选

## 3. 发现

### 3.1 高风险：`detach` 路径仍然缺少持久化失败后的事务收口

相关位置：

- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:121)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:635)
- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:690)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:998)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1315)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1281)
- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:2694)
- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:3060)

问题本质：

- `apply_persisted_runtime_state_message_locked(...)` 的顺序仍是“先改内存，再落盘”。
- `detach_binding_locked(...)` / `detach_thread_bindings_locked(...)` 在那之前又会先做可见副作用：
  - 释放 interaction lease
  - 取消本地订阅
  - 取消 patch / watchdog timer
- 一旦 `ChatBindingStore.save(...)` 失败，当前流程不会回滚前面的状态变化。

这意味着：对外部观察者来说，`attached -> detached` 迁移并不是原子的。

#### 3.1.1 会在什么场景触发

前提不是“用户命令本身特殊”，而是**正好在 detach 过程中遇到持久化失败**。

最常见的失败来源会是：

1. `chat_bindings.json` 现有内容损坏，`save()` 内部重新读文件时抛错。
2. `chat_bindings.json.tmp` 写入失败，例如磁盘写满、目录权限异常。
3. `os.replace(...)` 失败，例如目标路径权限或文件系统状态异常。

只要这些失败发生在 detach 过程中，就会触发这条事务缺口。

#### 3.1.2 用户使用路径

这条问题不是只会被一个命令触发；它覆盖了所有以 detach 作为中间步骤的管理路径。

直接用户路径：

1. 飞书里当前会话执行 `/detach`
   - 路由入口在 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:1538)
   - 实际执行走 [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1252) -> [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:998)

2. 本地执行 `feishu-codexctl binding detach <binding_id>`
   - 对应合同见 [docs/contracts/feishu-codexctl-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-codexctl-command-matrix.zh-CN.md:71)
   - 实际仍走 `detach_binding(...)`

3. 本地执行 `feishu-codexctl thread detach --thread-id ...` 或 `--thread-name ...`
   - 对应合同见 [docs/contracts/feishu-codexctl-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-codexctl-command-matrix.zh-CN.md:102)
   - 实际走 [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1315)
   - 这条路径更糟一点：如果它判断“需要先对 backend 做 unsubscribe”，会先调用 `_unsubscribe_thread(...)`，再进入 `detach_thread_bindings_locked(...)` [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1318)

间接用户路径：

4. 飞书或本地执行 backend reset
   - 飞书 `/reset-backend`
   - 本地 `feishu-codexctl service reset-backend`
   - 对应合同见 [docs/contracts/feishu-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-command-matrix.zh-CN.md:57) 和 [docs/contracts/feishu-codexctl-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-codexctl-command-matrix.zh-CN.md:61)
   - 当前实现会在 reset 前批量 detach 当前实例的 attached bindings [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:2703)

5. backend websocket 断开后的自动 fail-close
   - 入口在 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:3060)
   - 当前实现会自动调用 `fail_close_service_attached_runtime()`，内部同样走 `detach_thread_bindings_locked(...)` [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1281)

换句话说，这不是一条“很偏的手工命令 bug”，而是所有 detach 语义共用 owner 上的事务边界没有彻底收口。

#### 3.1.3 用户会看到什么

如果失败正好发生在上述路径里，用户可能看到：

1. 当前操作返回失败。
2. 当前进程内存里，这个 binding 已经像 `detached`。
3. 当前服务也可能已经不再把它当 attached subscriber。
4. 但服务重启后，又会从 `chat_bindings.json` 读回 `attached`。

也就是说，三层状态会裂开：

- 内存态：`detached`
- 运行态订阅 / owner：已释放或已撤掉
- 落盘态：仍是 `attached`

这直接违反了仓库自己偏好的“单一事实源”和“fail-closed 行为”。

#### 3.1.4 当前缺的回归

目前已有的回归主要覆盖了：

- `bind_thread_locked(...)` 持久化失败回滚
- `clear_thread_binding_locked(...)` 持久化失败回滚

对应位置：

- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:278)
- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:357)
- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:401)

但我没有看到同等级别覆盖：

- `detach_binding_locked(...)` 在 `save()` 失败时必须回滚
- `detach_thread_bindings_locked(...)` 在批量 detach 中任一 `save()` 失败时必须回滚
- `thread detach` 路径在提前 `_unsubscribe_thread(...)` 后若持久化失败，如何补偿
- `service reset-backend` / websocket disconnect 的 detach 失败收口

#### 3.1.5 建议修法

建议不要继续在调用方补“遇错再补几刀”，而是直接把 detach owner 自身改成事务式：

1. 先用 staged state 计算目标状态。
2. 先完成持久化。
3. 持久化成功后，再提交：
   - runtime state
   - subscriber 集合
   - interaction lease 释放
   - timer 取消
4. 如果必须先做外部副作用，则需要显式补偿逻辑，把旧 attached 事实完整恢复回来。

### 3.2 高风险：`binding clear` / `archive` 路径也存在事务缺口

相关位置：

- [bot/binding_runtime_manager.py](/home/zlong/llm/feishu-codex/bot/binding_runtime_manager.py:402)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:526)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)
- [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1350)

问题本质：

- `deactivate_binding_locked(...)` 先把 binding 从内存态 `pop` 掉，再调用
  `ChatBindingStore.clear(...)`。
- 如果 `clear(...)` 失败，函数会在释放 interaction lease、取消本地订阅之前异常退出。
- 结果就是：
  - 内存态已经不像这个 binding 还存在
  - 订阅态和 lease 态却还留着
  - 落盘 bookmark 也仍然还在

这意味着：`binding clear` 这类看似本地的 bookmark 管理动作，在失败路径上也不是原子的。

#### 3.2.1 会在什么场景触发

触发条件和 `detach` 路径类似，核心仍是：

1. `chat_bindings.json` 现有内容损坏，`clear()` 内部重新读文件时报错。
2. 临时文件写入或最终替换失败，例如磁盘写满、目录权限异常。
3. 归档或清理 binding 的过程中正好遇到这些存储失败。

#### 3.2.2 用户使用路径

直接用户路径：

1. 本地执行 `feishu-codexctl binding clear <binding_id>`
   - 入口在 [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:526)

2. 本地执行 `feishu-codexctl binding clear-all`
   - 入口在 [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:550)

3. 飞书里执行 `/archive`
   - 路由入口在 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:1609)
   - 实际执行走 [bot/runtime_admin_controller.py](/home/zlong/llm/feishu-codex/bot/runtime_admin_controller.py:1350)

4. 本地执行 `feishu-codexctl thread archive --thread-id ...` 或 `--thread-name ...`
   - 对应合同见 [docs/contracts/feishu-codexctl-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-codexctl-command-matrix.zh-CN.md:100)
   - 实际仍走 `archive_thread_for_control(...)`

#### 3.2.3 用户会看到什么

如果失败发生在这些路径里，用户可能看到：

1. 操作返回失败。
2. 当前进程内存里，这个 binding 又像是已经被清掉。
3. 但 thread subscriber / interaction owner 还可能留着。
4. 服务重启后，bookmark 又会从 `chat_bindings.json` 读回来。

对 `archive` 来说，坏结果还会更进一步：

5. backend 侧 thread 可能已经先被归档。
6. 但本地 binding 清理却只做了一半。

这会形成另一种单一事实源破裂：

- 内存态：像“已清掉”
- 订阅 / lease 态：像“未清掉”
- 落盘态：像“未清掉”
- archive 路径上，远端 thread 事实还可能已经先变化

#### 3.2.4 当前缺的回归

当前我看到的回归更偏 happy path：

- [tests/test_binding_runtime_manager.py](/home/zlong/llm/feishu-codex/tests/test_binding_runtime_manager.py:219)
- [tests/test_runtime_admin_controller.py](/home/zlong/llm/feishu-codex/tests/test_runtime_admin_controller.py:326)

但没有同等级别覆盖：

- `deactivate_binding_locked(...)` 在 `clear()` 失败时必须回滚
- `clear_binding_for_control(...)` 失败后不得留下半状态
- `archive_thread_for_control(...)` 在远端 archive 后本地清理失败时如何补偿

#### 3.2.5 建议修法

建议把这条 owner 也收口成和 `bind_thread_locked(...)` / `clear_thread_binding_locked(...)`
同等级别的事务实现：

1. 先保留旧快照，不要先 `pop` live state。
2. 先完成 bookmark 持久化清理。
3. 只有持久化成功后，再提交：
   - runtime state 删除
   - subscriber 清理
   - interaction lease 释放
4. `archive_thread_for_control(...)` 应避免“先远端 archive，再本地清理”的顺序，或至少补齐失败补偿。

### 3.3 已收口：开发测试入口对 bare `pytest` 的不自洽

这条在当前工作树上已经不应继续列为问题。

当前状态：

1. 仓库已在 [pyproject.toml](/home/zlong/llm/feishu-codex/pyproject.toml:38) 固化 `pytest` 的 repo-root 导入路径。
2. 仓库已提供 [requirements-dev.txt](/home/zlong/llm/feishu-codex/requirements-dev.txt:1) 作为新环境的最小测试依赖入口。
3. 当前我已实测：
   - `pytest -q`
   - `python -m pytest -q`
   两者都能直接通过 `797` 个测试。

因此，这条更准确的表述应该是：

- **历史上存在过 bare `pytest` 不自洽的问题**
- **当前工作树已经把它收口**

### 3.4 补充观察：`fcodex resume` 的本地重连窗口值得继续盯住

这条目前不是“当前稳定失败的 bug”，但它和日常主路径高度相关。

#### 3.4.1 会在什么场景触发

它只会出现在本地 `fcodex` 继续既有 thread 的路径上，尤其是：

1. `fcodex resume <thread_id>`
2. `fcodex resume <thread_name>`

其中第 2 条在名字解析结束后，最终也会进入同一条 resume-style remote reconnect 路径，合同见：

- [docs/contracts/local-command-and-thread-profile-contract.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/local-command-and-thread-profile-contract.zh-CN.md:71)

#### 3.4.2 用户使用路径

最典型路径是：

1. 用户先在飞书里已有一个 thread
2. 本地想继续它，执行 `fcodex resume <thread_id|thread_name>`
3. upstream remote client 先连一次做 lookup / session establish
4. 断开
5. 很快再重连进入正式 TUI

proxy 自己也明确写了这个运行前提：

- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py:995)

#### 3.4.3 用户会看到什么

如果这个 race 真的打中，用户看到的不会是飞书侧异常，而是：

1. `fcodex resume` 启动失败
2. 本地第二次 websocket 连接被拒绝
3. 体感上像“resume 偶发地起不来”

它不会主要体现在：

- 飞书普通提问
- `feishu-codexctl` thread 查询
- 安装 / 配置 / 重启服务

它主要打在本地继续 live thread 这条主路径上。

#### 3.4.4 当前判断

截至这次更新，我的判断是：

- 这是**已观测到一次**的时序型失败
- 当前更像 flake / race 候选
- 因为复跑已经全部通过，所以暂时不把它和 `detach` 事务缺口放在同一级别

但如果后续在慢机器、CI、WSL、系统负载高、或 websocket 接受连接有抖动的环境里再次出现，就应优先把它提升成正式缺陷。

## 4. 一句话结论

截至 2026-05-12 当前工作树，我确认这轮审视里仍成立的实质 correctness 风险有两条：

1. `detach` 共享实现上的事务缺口。
2. `binding clear` / `archive` 路径在 bookmark 清理失败时的事务缺口。

`pytest` 入口不一致问题已经在当前工作树收口；另有一条需要继续盯住的主路径观察，是 `fcodex resume` 的 resume-style reconnect 时序窗口。
