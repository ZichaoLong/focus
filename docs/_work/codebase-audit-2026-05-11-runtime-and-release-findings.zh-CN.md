# `feishu-codex` runtime / 发布面审视记录

日期：2026-05-11

## 1. 范围

本文记录本轮补充审视里，和以下主题直接相关的真实问题：

- live runtime lease / cross-instance 协调
- thread-wise memory mode 的 direct-write 语义
- 安装包内置 managed skill 的发布完整性
- daemon 入口测试的有效性

不重复展开本文之外、已经有单独记录的内容：

- `shared_command_surface` 的“事实源”表述问题
- `CodexSettingsDomain` 的 `list_models` 测试回归

## 2. 本轮实际检查

### 2.1 使用的解释器

- `python3`（当前环境：`Python 3.14.4`）

### 2.2 实际执行过的检查

纯 Python 测试：

```bash
python3 -m unittest tests.test_thread_runtime_lease_store tests.test_thread_runtime_coordination -q
python3 -m unittest tests.test_main.MainEntrypointTests.test_main_uses_five_second_default_feishu_request_timeout -q
python3 -m unittest discover -s tests -q
```

最小复现：

- 用 `ThreadRuntimeLeaseStore` 直接构造“同实例、不同 `service_token`”的 holder 混合场景
- 读取当前源码树中的 `egg-info/SOURCES.txt`，核对 managed skill 是否进入打包清单

### 2.3 当前环境限制

当前解释器里缺少：

- `lark_oapi`
- `websockets`
- `pip`

因此：

- 无法在这个解释器里完整跑依赖相关测试
- 也无法直接构建 wheel 做二次验证

但下文列出的 4 条问题，均已通过静态链路核对或最小复现确认，不依赖上述第三方包是否安装。

## 3. 结论摘要

### 3.1 已确认问题

1. `ThreadRuntimeLeaseStore` 会把同实例、不同 `service_token` 的 holder 合并进同一条 lease，导致 service 重启后的旧 holder 残留。
2. thread-wise memory mode 的 direct-write 路径与它自己的 next-load 语义不一致，且 `off` / `read` 在 direct-write 路径上会被压成同一个 backend 值。
3. 发布元数据漏掉了 `feishu-scheduled-prompts` 的 skill 资源；按当前官方安装路径安装后，`feishu-codex skill install` 有较高概率拿不到完整资源。
4. daemon 入口默认超时的单元测试本身失效，当前并没有真正保护 `5.0s` 的默认值。

### 3.2 优先级判断

- 前两条属于 correctness / runtime 收口问题，应优先修。
- 第三条属于 release / packaging 问题，影响安装后能力完整性，应在下次发布前修掉。
- 第四条优先级较低，但它削弱了入口参数合同的测试保护，应顺手修复。

## 4. 详细发现

### 4.1 P0: 同实例不同 `service_token` 的 runtime lease 会被混合，service 重启后可能遗留脏 owner

涉及代码：

- [bot/stores/thread_runtime_lease_store.py](../../bot/stores/thread_runtime_lease_store.py:121)
- [bot/stores/thread_runtime_lease_store.py](../../bot/stores/thread_runtime_lease_store.py:354)
- [bot/thread_runtime_coordination.py](../../bot/thread_runtime_coordination.py:300)

当前行为链路：

1. `ThreadRuntimeLeaseStore.acquire()` 只要 `instance_name` 相同，就允许追加 holder。
2. 这里不会检查 `owner_service_token` 是否也相同。
3. 于是“旧 service token 下的 `fcodex` holder”与“新 service token 下的 service holder”会被写进同一条 lease。
4. 后续 backend reset 时，[bot/codex_handler.py](../../bot/codex_handler.py:2601) 只会按**当前** `owner_token` 调 `purge_all_for_instance()`。
5. 结果是新 token 对应的 holder 被清掉，但旧 token holder 仍残留。
6. 而自动转移路径又要求 registry token 与 lease token 完全一致，[bot/thread_runtime_coordination.py](../../bot/thread_runtime_coordination.py:311) 会把这种状态判定为“记录中的 owner service 已变化”。

我实际做过的最小复现：

1. 先写入：
   - `instance=default`
   - `holder_id=fcodex:1`
   - `owner_service_token=token-old`
2. 再写入：
   - `instance=default`
   - `holder_id=service:token-new`
   - `owner_service_token=token-new`
3. `lease` 最终会同时保留：
   - `('fcodex:1', 'token-old')`
   - `('service:token-new', 'token-new')`
4. 再执行：
   - `purge_all_for_instance(instance_name='default', owner_service_token='token-new')`
5. 剩余 holder 仍是：
   - `('fcodex:1', 'token-old')`

这说明当前 store 并没有维持“同一实例同一代 service owner”的不变量。

为什么这是 correctness 问题：

- 代码其他地方显然把 `owner_service_token` 当作 service 世代边界看待。
- 但 lease store 本身没有维护这条边界。
- 结果会出现：
  - 旧 `fcodex` holder 冒充当前 live owner
  - backend reset 后仍然留有脏 lease
  - 跨实例 auto-transfer 被误判为不可转移

建议：

1. `ThreadRuntimeLeaseStore.acquire()` 在“同实例但 token 不同”时，不应直接合并 holder。
2. 更稳妥的收口方式是：
   - 要么显式拒绝并要求上层先清旧代 holder
   - 要么在确认旧代 owner 已失效后，把整条 lease 原子替换为新代 owner
3. 需要补一组覆盖：
   - same instance + different token
   - reset backend 后旧 token holder 不得残留

### 4.2 P0: thread-wise memory mode 的 direct-write 路径与 next-load 合同不一致

涉及代码：

- [bot/runtime_admin_controller.py](../../bot/runtime_admin_controller.py:1666)
- [bot/codex_handler.py](../../bot/codex_handler.py:2704)
- [bot/thread_memory_mode.py](../../bot/thread_memory_mode.py:35)

当前语义冲突点：

1. `plan_thread_memory_mode_update()` 把 direct-write 条件定义成：
   - thread 已 `verifiably globally unloaded`
   - 因而“可直接写入 thread-wise memory mode”
2. 但真正执行 direct-write 时，`_apply_thread_memory_mode()` 并不只是写持久化 store。
3. 它还会立刻调用 adapter 的：
   - `thread/memoryMode/set`

这和“thread-wise next-load 设置”的合同不一致。

更严重的是，[bot/thread_memory_mode.py](../../bot/thread_memory_mode.py:35) 里：

- `off -> disabled`
- `read -> disabled`
- `read_write -> enabled`

也就是说：

- direct-write 路径即使 RPC 成功
- backend 也表达不了 `off` 和 `read` 的区别

这带来的问题不是“实现方式不好看”，而是语义已经不自洽：

- direct-write 条件成立时，thread 按定义应该已经 unloaded
- 此时应只更新“下次加载时使用的持久化值”
- 不应该再把一个语义已经降维的值推给当前 backend

建议：

1. 把 thread-wise memory mode 的 direct-write 路径收口成纯持久化写入。
2. 只有在“通过 reset backend 让当前实例重新收敛”这条路径上，才去碰 backend 当前代状态。
3. 补充回归测试覆盖：
   - `off`
   - `read`
   - `read_write`
   三种模式在 direct-write 路径上都不得依赖当前 backend 的即时 RPC 表达语义。

### 4.3 P1: `feishu-scheduled-prompts` 的 managed skill 资源没有进入当前打包清单

涉及代码与元数据：

- [pyproject.toml](../../pyproject.toml:29)
- [bot/manage_cli.py](../../bot/manage_cli.py:341)
- [install.py](../../install.py:83)
- [feishu_codex.egg-info/SOURCES.txt](../../feishu_codex.egg-info/SOURCES.txt:70)

当前问题链路：

1. 发布配置只声明了：
   - `bot.managed_skills.feishu_send_image`
2. 没声明：
   - `bot.managed_skills.feishu_scheduled_prompts`
   - 及其 `skill/agents/*`
   - `skill/scripts/*`
3. 但 `feishu-codex skill install` 的源目录解析逻辑是：
   - import 已安装包
   - 再从包目录下取 `skill/`
4. 官方安装入口 [install.py](../../install.py:95) 又正是把当前仓库 `pip install` 到受管 `.venv`

当前仓库里现成的 `egg-info/SOURCES.txt` 已经显示：

- 有 `feishu_send_image`
- 没有 `feishu_scheduled_prompts`

这说明至少在当前元数据状态下，scheduled-prompts 的 skill payload 没有被完整纳入包资源清单。

为什么这是发布面问题：

- 在源码树里运行测试时，[tests/test_manage_cli.py](../../tests/test_manage_cli.py:491) 会通过，因为它直接从当前仓库取文件。
- 但真实用户安装后运行 `feishu-codex skill install`，依赖的是“安装包里是否带上了这些资源”。
- 这两条路径现在并不等价。

建议：

1. 把 `feishu_scheduled_prompts` 的以下资源纳入 package-data / MANIFEST：
   - `skill/SKILL.md`
   - `skill/agents/openai.yaml`
   - `skill/scripts/manage_scheduled_prompt.py`
   - `skill/scripts/__init__.py`
2. 增加一条真正面向已安装包的回归检查，而不是只比对源码树。

### 4.4 P2: daemon 入口默认超时的单测本身失效，保护层实际不存在

涉及代码：

- [tests/test_main.py](../../tests/test_main.py:11)

当前现象：

```bash
python3 -m unittest tests.test_main.MainEntrypointTests.test_main_uses_five_second_default_feishu_request_timeout -q
```

会直接失败于：

- `patch("bot.standalone.CodexBot", ...)`

错误为：

- `AttributeError: module 'bot' has no attribute 'standalone'`

因此这条测试根本没有真正跑到：

- `request_timeout_seconds=5.0`

的断言。

这条问题优先级不高，但它意味着：

- `bot.__main__` 的默认 timeout 合同目前没有被自动验证

建议：

1. 改成 patch 当前入口实际导入到的对象路径。
2. 修复后把它保留成单测，不建议删掉。

## 5. 已验证但暂未扩展处理的部分

本轮还确认了两件事：

1. [tests/test_thread_runtime_lease_store.py](../../tests/test_thread_runtime_lease_store.py:1) 和 [tests/test_thread_runtime_coordination.py](../../tests/test_thread_runtime_coordination.py:1) 当前都没有覆盖“同实例不同 token”的场景。
2. `python3 -m unittest discover -s tests -q` 在当前解释器里还有一批导入错误，主要来自缺少 `lark_oapi` / `websockets`，所以本轮结论不依赖这些测试是否能在此环境跑通。

## 6. 建议优先级

建议处理顺序：

1. 先修 runtime lease 的 token 世代混合问题。
2. 再修 thread-wise memory mode 的 direct-write 语义。
3. 然后补齐 scheduled-prompts 的打包资源。
4. 最后修 `tests/test_main.py` 的 patch 路径。

## 7. 一句话判断

这轮最值得优先处理的不是“代码风格”或“结构抽象”，而是两条会直接破坏运行态合同的不变量：

- **live runtime owner 的 service 世代边界没有被 lease store 维护**
- **thread-wise memory mode 的 direct-write 路径没有严格遵守 next-load 语义**

这两条修完之后，再处理发布面和测试保护层，收益最高。
