# `feishu-codex` 非架构审视记录

日期：2026-05-11

## 1. 范围

本文只记录这轮审视里**不属于架构边界重构**的部分：

- 测试回归
- 命令面事实源表述
- 文档与代码路由一致性
- 依赖告警

不展开讨论：

- `CodexHandler` / controller / manager 的进一步拆分方案
- binding / runtime / turn lifecycle 的职责收口方案

## 2. 本轮实际检查

### 2.1 使用的解释器

- `/home/zlong/anaconda3/bin/python`

### 2.2 执行过的测试

全量：

```bash
/home/zlong/anaconda3/bin/python -m pytest -q tests
```

单文件复核：

```bash
/home/zlong/anaconda3/bin/python -m pytest -q tests/test_codex_settings_domain.py
```

## 3. 结论摘要

### 3.1 已确认问题

1. `CodexSettingsDomain` 的单元测试已经整体失效。
2. `shared_command_surface.py` 把自己表述成“Feishu slash 命令事实源”，但它实际上只覆盖一部分命令。

### 3.2 已确认没坏的部分

本轮核对下列三份内容后，没有发现实际命令集合不一致：

- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:1480) 中的路由表
- [docs/contracts/feishu-command-matrix.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-command-matrix.md:30)
- [bot/codex_help_domain.py](/home/zlong/llm/feishu-codex/bot/codex_help_domain.py:675) 中的 `/commands`

也就是说，当前问题更像是：

- **测试保护层坏了**
- **“谁是事实源”的表述不精确**

而不是正式命令面已经互相打架。

## 4. 详细发现

### 4.1 高优先级：`CodexSettingsDomain` 测试回归

现象：

- `tests/test_codex_settings_domain.py` 单文件 23 个失败
- 根因一致：`SettingsDomainPorts` 新增了必填的 `list_models`
- 但测试 stub 构造还停留在旧合同

相关位置：

- [bot/codex_settings_domain.py](/home/zlong/llm/feishu-codex/bot/codex_settings_domain.py:64)
- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:382)
- [tests/test_codex_settings_domain.py](/home/zlong/llm/feishu-codex/tests/test_codex_settings_domain.py:220)

这不是纯粹的“测试文件忘记更新”。
失效的正好是当前最敏感的一组合同：

- `/profile`
- `/memory`
- `apply_*_with_backend_reset`
- thread-wise next-load state 相关拒绝/短路/重算行为

这意味着当前仓库里，最需要回归保护的设置面，实际上没有被自动验证。

建议：

1. 先把 `_SettingsPortsStub` 补齐 `list_models`，恢复这 23 个测试的可运行性。
2. 在这个文件里补上 `/model` 的 domain 级单测，而不是只依赖 handler 级覆盖。

补充观察：

我在 `tests/test_codex_settings_domain.py` 里没有看到针对 `handle_model_command` / `handle_set_model` 的直接单测；当前 `/model` 主要依赖 [tests/test_codex_handler.py](/home/zlong/llm/feishu-codex/tests/test_codex_handler.py) 做表层覆盖。

### 4.2 中优先级：`shared_command_surface` 的定位写得过满

文件头当前写法：

- “Feishu 侧一等 slash 命令事实源”

相关位置：

- [bot/shared_command_surface.py](/home/zlong/llm/feishu-codex/bot/shared_command_surface.py:2)

但它当前只覆盖一部分命令，例如未覆盖：

- `/status`
- `/new`
- `/approval`
- `/sandbox`
- `/permissions`
- `/collab-mode`
- `/whoami`
- `/bot-status`
- `/group`
- `/group-mode`

真正的完整正式命令集合目前仍在：

- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py:1480)
- [docs/contracts/feishu-command-matrix.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-command-matrix.md:30)

因此这里的问题不是功能错误，而是**命名/注释让维护者产生错误预期**。

建议二选一：

1. 把 `shared_command_surface.py` 的表述收窄，明确它只是 help / card / copy 复用的一组“共享命令片段”。
2. 如果真想让它成为事实源，就需要把完整命令集合收进去，并让 `/commands`、help 文案、合同文档尽量从同一份数据导出。

短期更建议第 1 种，因为改注释/命名的风险最低。

### 4.3 中低优先级：正式命令面当前是对齐的，不建议无故再 churn

我这轮把三处做了命令集合核对：

- handler 路由
- `/commands` 文本
- `feishu-command-matrix.md`

结果是：

- 代码路由与合同文档集合一致
- `/commands` 文案也没有看出明显漏项

这条记录的意义是：

- 当前不需要为“命令面已经失真”做大手术
- 重点应该是修测试、收窄事实源表述

否则容易把精力花在“看起来要统一”，但实际没坏的地方。

### 4.4 低优先级：测试时有依赖层 deprecation warnings

本轮 pytest 里出现了几类告警：

- `pkg_resources is deprecated`
- `websockets.legacy is deprecated`
- `websockets.InvalidStatusCode is deprecated`
- `datetime.datetime.utcfromtimestamp()` deprecation

来源主要在当前环境的第三方依赖：

- `lark_oapi`
- `websockets`
- `pkg_resources`

这暂时不像是本项目自己的 correctness bug，但建议把它们记录为后续依赖清理项，避免以后升级 Python 或依赖时一起爆。

## 5. 建议优先级

### 5.1 建议立刻做

1. 修复 [tests/test_codex_settings_domain.py](/home/zlong/llm/feishu-codex/tests/test_codex_settings_domain.py:220) 的 `SettingsDomainPorts` 构造。
2. 给 `CodexSettingsDomain` 补 `/model` 直接单测。

### 5.2 建议随后做

1. 收窄 [bot/shared_command_surface.py](/home/zlong/llm/feishu-codex/bot/shared_command_surface.py:2) 的注释/命名，避免继续误导。
2. 如仍保留这层抽象，可在文件或合同文档里明确：
   - 它不是完整命令事实源
   - 它只服务于 help / card / copy 复用

### 5.3 当前不建议优先做

1. 不建议仅因“看起来可以更统一”就重写整套命令注册机制。
2. 不建议在没有新增收益的情况下，强行把所有命令都塞进 `shared_command_surface`。

## 6. 一句话判断

当前非架构层面的核心问题不是“产品面已经乱了”，而是：

- **测试保护层掉了**
- **某个‘事实源’文件的自我定位写得比实际能力更大**

先修这两点，收益最高。
