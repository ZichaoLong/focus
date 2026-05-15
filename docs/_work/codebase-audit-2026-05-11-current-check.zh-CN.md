# `feishu-codex` 当前状态复核记录

日期：2026-05-11

## 1. 范围

本文不是重新做一轮全新架构审计，而是复核当前 `main` 工作树在 2026-05-11 这一天的真实状态，回答三个问题：

1. 之前记录过的问题今天是否仍然成立。
2. 当前仓库是否存在明确可复现的 correctness 风险。
3. 当前测试面是否整体处于健康状态。

## 2. 实际检查

### 2.1 测试

在仓库根目录执行：

```bash
python -m pytest -q tests
```

结果：

- `770 passed`
- 无失败
- 仅有第三方依赖告警与 `fork()` 相关测试告警

另外单独复核了：

```bash
python3 -m unittest tests.test_thread_runtime_lease_store tests.test_thread_runtime_coordination -q
python3 -m unittest tests.test_main.MainEntrypointTests.test_main_uses_five_second_default_feishu_request_timeout -q
```

也均通过。

### 2.2 代码链路复核

重点复核了以下位置：

- [bot/stores/thread_runtime_lease_store.py](../../bot/stores/thread_runtime_lease_store.py:121)
- [bot/thread_runtime_coordination.py](../../bot/thread_runtime_coordination.py:303)
- [bot/codex_handler.py](../../bot/codex_handler.py:2600)
- [pyproject.toml](../../pyproject.toml:29)
- [tests/test_main.py](../../tests/test_main.py:12)
- [bot/shared_command_surface.py](../../bot/shared_command_surface.py:1)

### 2.3 最小复现

我用 `ThreadRuntimeLeaseStore` 直接构造了“同实例名、不同 `service_token` 的混合 holder 记录”，然后执行：

```python
purge_all_for_instance(instance_name="default", owner_service_token="token-new")
```

复现结果：

- 新代 holder 被清掉
- 旧代 `fcodex` holder 仍残留
- 后续 `preview_thread_runtime_holder_acquire(...)` 会返回 `allowed=False`
- 原因是：`owner service 已变化`

这说明 token 代际残留一旦进入 lease 文件，当前清理路径无法把它彻底收口。

## 3. 当前结论

## 3.1 仍然成立的明确问题

### 高风险：`ThreadRuntimeLeaseStore` 的 token 定向 purge 无法彻底清掉同实例旧代 holder

相关位置：

- [bot/stores/thread_runtime_lease_store.py](../../bot/stores/thread_runtime_lease_store.py:310)
- [bot/stores/thread_runtime_lease_store.py](../../bot/stores/thread_runtime_lease_store.py:361)
- [bot/thread_runtime_coordination.py](../../bot/thread_runtime_coordination.py:314)
- [bot/codex_handler.py](../../bot/codex_handler.py:2600)

问题本质：

- `service_token` 被项目当作 service 世代 fence。
- 但 `purge_instance()` / `purge_all_for_instance()` 的行为是：
  - 删除“名字匹配且 token 匹配”的 holder
  - 保留“同名但旧 token”的 holder
- 一旦 lease 文件中已经混入旧代 holder，当前代 reset / purge 并不能把它清干净。

这会导致：

1. 当前 service 自己做了 backend reset。
2. 它按自己的 `owner_token` 清理 lease。
3. 旧代 `fcodex` holder 仍留在文件里。
4. 后续 attach / acquire 预检会看到：
   - owner instance 还是这个实例名
   - 但 owner token 已不是 registry 里当前 service token
5. 于是流程 fail-closed，提示 `owner service 已变化`。

这个问题今天依然没有对应回归测试。现有测试只覆盖了：

- 同实例不同 token 的 acquire 会被拒绝

但没有覆盖：

- token 定向 purge 后旧代 holder 不得残留

白话场景：

1. 你本地原来开着一个旧的 `fcodex` TUI，它属于旧一代 service。
2. 之后你重启了 `feishu-codex` service，service token 变了。
3. 新 service 正常起来了，也正常接管了 registry 里的“当前代 service 身份”。
4. 这时你再做一次 `reset-backend`，或尝试让当前实例重新 attach / acquire 某个 thread。
5. 从用户视角看，你会以为“都已经是同一个实例了，旧状态应该被这次 reset 一起清干净”。
6. 但实际上 lease 文件里还可能残留一条“同实例名、旧 token”的旧 holder。
7. 后续预检再读到它时，就会进入一种很别扭的状态：
   - 实例名还是这个实例
   - 但 service 世代对不上
   - 最终被 fail-close，报“owner service 已变化”

为什么这条值得单独记：

- 这不是单纯的“脏数据没清干净”。
- 它更像是：项目的其他层已经把 `service_token` 当成 service 世代 fence 了，但 lease store 自己没有维护这条不变量。
- 所以问题不是出在某个提示文案上，而是 runtime 身份模型本身在 store 层被打穿了。
- 用户面最直观的体验会是：
  - “明明刚 reset 过，为什么还是说 owner 变了？”
  - “明明是同一个实例，为什么还要我再手动处理一轮？”

建议修法：

1. 明确 store 不变量：
   - 同一条 lease 里不应长期保留同实例的多代 token holder。
2. 对 purge 路径做代际收口：
   - 若命中当前实例当前 token，则应同时判定并清理同实例旧 token holder；
   - 或在确认只剩旧代 holder 时直接整条 lease fail-closed 清空。
3. 补回归测试覆盖：
   - `purge_instance`
   - `purge_all_for_instance`
   - purge 后重新 attach / acquire 可恢复

## 3.2 已不再成立的旧结论

下列旧审计结论在当前工作树里已失效，不应再当成现状引用：

1. `feishu-scheduled-prompts` 打包资源缺失
   - 当前 [pyproject.toml](../../pyproject.toml:29) 已声明该 skill 的 package data。
   - 当前 `feishu_codex.egg-info/SOURCES.txt` 也已包含相关资源。

2. `tests/test_main.py` 默认超时测试失效
   - 当前 [tests/test_main.py](../../tests/test_main.py:12) 可通过。
   - `bot/__main__.py` 里默认值仍正确读取 `DEFAULT_FEISHU_REQUEST_TIMEOUT_SECONDS`。

3. `shared_command_surface.py` 自称完整事实源
   - 当前文件头已经明确写成“共享片段，不是完整命令路由事实源”。

4. `tests/test_codex_settings_domain.py` 整体失效
   - 当前 pytest 全量通过，说明该回归已被修复。

## 3.3 当前剩余的低优先级事项

本轮看到的警告主要来自第三方依赖，而非本仓库自己的 correctness 失败：

- `pkg_resources` deprecation
- `websockets.legacy` deprecation
- `websockets.InvalidStatusCode` deprecation
- `datetime.utcfromtimestamp()` deprecation

另外，部分并发测试在 Python 3.13 下会提示多线程进程里使用 `fork()` 可能有死锁风险；这目前只体现在测试告警层，不构成已确认产品缺陷，但值得后续留意。

## 4. 一句话结论

截至 2026-05-11 当前工作树，`feishu-codex` 的整体测试面是健康的，之前记录过的若干发布/测试问题已经修复；当前我仍确认存在的核心 correctness 风险，只剩 runtime lease 在同实例跨 service 世代下的 purge 收口不完整这一条。
