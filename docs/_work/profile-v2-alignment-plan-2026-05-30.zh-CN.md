# profile-v2 对齐改造清单

## 背景

上游 Codex 已把 `--profile/-p` 明确切到 profile-v2 语义：

- `--profile work` 选择的是 `${CODEX_HOME}/work.config.toml`
- 基础层仍然是 `${CODEX_HOME}/config.toml`
- 选中的 profile-v2 文件作为额外 user layer 叠加在基础 user layer 之上

本项目当前仍残留一套 legacy profile 语义：

- 从 `${CODEX_HOME}/config.toml` 的 `[profiles.<name>]` 读取 `model / model_provider`
- 在 `thread/start` / `thread/resume` 时把 `config.profile = "<name>"` 发给上游
- 通过 `config/batchWrite keyPath=profile` 试图改写当前 active profile

这三条都已与上游当前状态失配。

## 上游当前行为

### 1. 基础配置与 profile-v2

上游配置层顺序为：

- system
- user `${CODEX_HOME}/config.toml`
- selected profile `${CODEX_HOME}/<name>.config.toml`
- cwd / tree / repo project config
- runtime overrides

其中 profile-v2 的名字只是“选择哪个额外 user config 文件”的 selector，不再是 `config.toml` 里的 legacy 表。

### 2. 何时会因为 legacy profile 报错

不是“只要基础 `config.toml` 里有 legacy profile 就报错”。

更精确地说：

- 若没有显式使用 `--profile <name>`，上游不会因为基础 `config.toml` 里存在不相关的 `[profiles.*]` 而直接失败
- 若显式使用了 `--profile work`，且基础 `config.toml` 里还存在：
  - `profile = "work"`
  - 或 `[profiles.work]`
  上游会按 hard error 拒绝

因此，legacy profile 冲突是“按选中的同名 profile-v2 精确 fail-close”，不是“全局一刀切失败”。

### 3. 上游默认 profile / 默认配置

上游并不存在“默认 profile-v2 名字”这一概念。

若没有显式 `--profile <name>`：

- 只加载基础 `${CODEX_HOME}/config.toml`
- 顶层 `model`、`model_provider`、`model_reasoning_effort` 等字段直接生效

因此，若用户像当前机器这样把：

- `model = "gpt-5.5"`
- `model_provider = "custom"`
- `model_reasoning_effort = "xhigh"`

直接写在顶层，那么这就是无 profile-v2 选择时的默认基线。

### 4. 写 legacy profile 已不再被支持

上游 app-server 已明确拒绝：

- `config/batchWrite keyPath=profile`
- `config/batchWrite keyPath=profiles.*`

同时，legacy `profile = "..."` 也已不再被视为受支持的 canonical 配置写法。

## 本项目当前行为

### 1. 服务侧 app-server 重启后的默认基线

本项目服务侧启动 app-server 时，命令是：

- `codex app-server --listen ...`

不会附带 `--profile <name>`。

因此：

- `feishu-codex` 服务重启后，新 app-server 的默认基线就是上游基础 `${CODEX_HOME}/config.toml` 顶层配置
- 不是某个 profile-v2
- 也不是本项目当前 thread-wise profile store 中记录的 profile

### 2. 本项目已有的 thread-wise profile 合同

本项目已经形成了一套本地 thread-wise profile slice 合同：

- `profile`
- `model`
- `model_provider`

这套数据保存在本项目自己的 store 里，用于：

- cold `thread/resume`
- 新线程 seed
- turn/start 时的 model materialization

这层抽象本身可继续保留。

### 3. 当前失配点

当前仍有三条主链路停留在 legacy profile 世界：

- `bot/codex_config_reader.py`
  - 仍从 `${CODEX_HOME}/config.toml` 的 `[profiles.<name>]` 读 slice
- `bot/adapters/codex_app_server.py`
  - `thread/start` / `thread/resume` 仍向上游发送 `config.profile`
- `bot/fcodex_proxy.py`
  - 在真正 RPC 边界重写 payload 时，也仍把 `profile` 合并进 `params.config`

这意味着：

- 本项目虽然已经把 thread-wise profile slice 本地化了
- 但它在 materialize 到上游时，仍夹带 legacy profile 语义

### 4. 当前 `/profile` + `reset backend` 的真实效果

当前实现下，`/profile <name>` 再 `reset backend` 的效果，不是“让服务侧 app-server 以后都运行在该 profile-v2 上”。

更准确地说：

- `reset backend` 之后，新 app-server 仍按基础 `${CODEX_HOME}/config.toml` 顶层配置启动
- 本项目会把目标 thread 的 thread-wise profile slice 保存在本地 store
- 后续该 thread 真正 start / resume / turn 时，本项目再把 `model / model_provider` 注入进去

所以当前行为更接近：

- global runtime baseline 仍是 base config
- thread-local materialization 才承载 profile 效果

### 5. 当前 model catalog 的状态

当前本项目有一部分 model catalog / model list 提示逻辑，仍依赖 legacy profile reader。

因此在现状下：

- `/profile` + `reset backend` 不能被理解为“完整切换到了一个新的 profile-v2 运行时”
- 它更像是“后续线程 turn 尽量按该 profile 解析出的 `model / provider` 运行”
- profile-v2 专属的 model catalog 行为并没有在服务侧被完整 canonical 地采用

## 目标行为

本项目对齐后的目标应当是：

- 服务侧 app-server 的默认基线始终是基础 `${CODEX_HOME}/config.toml`
- profile-v2 只作为“解析 thread-wise profile slice”的名字来源
- 本项目不再向上游写入 legacy `config.profile` 或 `config.profiles`
- 本项目显式 profile 改写只 materialize 为：
  - `model`
  - `modelProvider`
- `/profile` 的候选来源改为 `${CODEX_HOME}/*.config.toml`
- 当前 thread 的 profile 名字由本项目本地 store 负责记忆和展示

这意味着本项目要明确区分两层：

- app-server 基线配置
- thread-wise profile materialization

而不是继续混用“当前 active profile”“legacy profile selector”“thread-wise profile 标签”这些概念。

## 实施清单

### A. profile-v2 读取层

- 重写 `bot/codex_config_reader.py`
- `resolve_profile_from_codex_config(profile_name)` 改为读取：
  - `${CODEX_HOME}/config.toml`
  - `${CODEX_HOME}/<profile_name>.config.toml`
- 解析规则改为：
  - selected profile file 优先
  - base config 顶层字段兜底
- 停止从 `[profiles.<name>]` 读取 `model / model_provider`
- 新增 `list_profile_v2_names()`：
  - 扫描 `${CODEX_HOME}/*.config.toml`
  - 排除基础 `config.toml`
- `resolve_profile_model_metadata()` 改到 profile-v2 文件语义

### B. 冲突校验

- 若显式解析 `profile_name = work`
- 且基础 `${CODEX_HOME}/config.toml` 中存在：
  - `profile = "work"`
  - 或 `[profiles.work]`
- 则按 fail-close 报错
- 文案与上游保持同口径：说明这是 legacy profile 冲突，需迁到 `work.config.toml`

### C. adapter RPC 边界

- 改 `bot/adapters/codex_app_server.py`
- `create_thread(..., profile=...)` 与 `resume_thread(..., profile=...)`
  不再向上游发送：
  - `config.profile`
- 只发送：
  - `model`
  - `modelProvider`
  - 其他真实需要的 `config_overrides`
- `set_active_profile()` 改为：
  - 明确 unsupported
  - 或直接删除调用面

### D. proxy 重写边界

- 改 `bot/fcodex_proxy.py`
- `_apply_new_thread_profile_seed()`
  不再把 `{"profile": setting.profile}` 合并回 `params.config`
- `_apply_saved_thread_profile_for_resume()`
  不再把 `profile_setting.profile` 合并回 `params.config`
- 所有“从 `params.config.profile` 取 hint”的逻辑改成本地变量传递
- `memory mode` 的 helper 不再依赖 legacy `profile` 字段作为中间信号

### E. 运行时展示与候选列表

- 改 `bot/adapters/codex_app_server.py` 的 `read_runtime_config()`
- 不再从 `config.read().config.profile` / `config.profiles` 推导：
  - `current_profile`
  - `profiles`
- 可选实现：
  - 通过 `config/read includeLayers=true` 从 user layer metadata 找 selected profile-v2 名字
  - 候选 profile 列表直接来自 `list_profile_v2_names()`
- 本项目展示“当前 profile”时，优先信任本地 thread-wise profile store

### F. `/profile` 领域逻辑

- 改 `bot/codex_settings_domain.py`
- `/profile` 的候选列表不再依赖 runtime `config.profiles`
- `/profile` 对某个名字的解析改为调用新的 profile-v2 reader
- `/profile` 卡片和帮助文本明确：
  - 这是当前 thread 的 thread-wise profile
  - 不是服务侧 app-server 的全局 active profile

### G. `fcodex -p`

- 改 `bot/fcodex.py`
- `-p/--profile` 仍然保留
- 但语义改为：
  - 解析 profile-v2 文件
  - 写入 thread-wise profile store
  - 真正 materialize 时只注入 `model / modelProvider`
- 不再把 wrapper 的 `--profile` 理解成可以经由 `config.profile` 传入 app-server

### H. 测试

- 改 `tests/test_codex_config_reader.py`
  - 基础 config + selected `<name>.config.toml` 叠加
  - base 顶层兜底
  - matching legacy conflict fail-close
  - unrelated legacy profile 允许
- 改 `tests/test_codex_app_server.py`
  - 不再断言 `thread/start` / `thread/resume` 发送 `config.profile`
  - 改断言为仅发送 `model` / `modelProvider`
  - 删除或改写 `set_active_profile_uses_config_batch_write`
- 改 `tests/test_codex_settings_domain.py`
  - `/profile` 候选来源改为本地 scanner
  - `/profile` 的“当前 profile”仍以本地 persisted thread setting 为准
- 改 `tests` 中 fake `config/read` 形状
  - 不再把 legacy `config.profile` / `config.profiles` 当成 canonical 来源

### I. 文档与帮助

- 改 `README.md`
- 改 `bot/shared_command_surface.py`
- 改 `bot/codex_help_domain.py`
- 文案统一说明：
  - base config 是服务基线
  - profile-v2 是 thread-wise profile 的名字来源
  - `/profile` 不会把服务侧 app-server 全局切到某个 profile-v2

## 不在本轮改动范围内

- 不尝试让服务侧 app-server 真正以某个 selected profile-v2 常驻运行
- 不把 thread-wise profile 直接映射成上游全局 active profile
- 不兼容本项目继续读取 legacy `[profiles.<name>]` 作为正常主路径

## 迁移后预期

迁移完成后，应满足：

- `feishu-codex` 服务重启后，默认仍吃基础 `${CODEX_HOME}/config.toml`
- `/profile work` 只改变当前 thread 的 thread-wise next-load / next-turn materialization
- `reset backend` 不改变全局基线，只确保后续 resume / start 用新 thread-wise profile slice
- profile-v2 的 `model / provider / catalog metadata` 通过本项目本地 reader 生效
- 本项目不再依赖上游已废弃的 legacy profile 写法
