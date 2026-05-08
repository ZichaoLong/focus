# 上游 Codex 高级功能接入飞书可行性分析 — 2026-05-08

Status: working material under `docs/_work/`. Not a repository fact.

2026-05-09 更新：

- 本文中关于 `memory mode` 的推荐方案已落地到正式命令面：
  - 飞书 `/memory [off|read|read_write]`
  - thread-wise 存储与 reset-backend 收口
  - 本地 `fcodex resume` 自动继承已持久化的 memory mode
- 当前仓库事实应以正式合同为准：
  - `docs/contracts/thread-memory-semantics.zh-CN.md`
  - `docs/contracts/feishu-command-matrix.zh-CN.md`
  - `docs/contracts/feishu-help-navigation.zh-CN.md`

## 1. 范围

本文收敛当前已确认的五个主题：

- `memory / memories`
- `skills`
- `plugins`
- `subagents / agents`
- `compact`

## 2. 目标

本文回答四个问题：

1. 上游 TUI 中这些功能分别作用在哪一层状态
2. 它们是“下一轮 turn 生效”还是“需要新 thread / 新 session”
3. 是否值得引入飞书
4. 如果引入，应该放到飞书哪一层入口

本文优先依据上游源码；公开文档可作为补充，但当前覆盖面略滞后于实现。

## 3. 上游事实

### 3.1 `memory / memories`

上游当前不是“单一 memory 开关”，而是三层混合模型：

- feature gate：`Feature::MemoryTool`
- 配置旋钮：
  - `memories.use_memories`
  - `memories.generate_memories`
- thread 元数据：`memory_mode`

源码事实：

- TUI `/memories` 不是临时切换；它会把设置写入 `config.toml`
- 若当前存在 `active_profile`，写入的是该 profile 下的 `memories.*`
- `use_memories` 只写配置，不 patch 当前 thread
- `generate_memories` 写配置后，还会调用 `thread/memoryMode/set` 更新当前 thread 的 `memory_mode`
- TUI 文案已经明确说明：
  - `Use memories ... Applied at next thread`
  - `Generate memories ... Current thread included.`
- app-server 已提供实验接口：
  - `thread/memoryMode/set`
  - `memory/reset`

因此，上游的真实语义是：

- `use_memories`：
  - 不是 thread-wise 热更新
  - 对当前已 materialized / loaded thread 不会立即生效
  - 需要新 thread 或重新 materialize
- `generate_memories`：
  - 有 thread 级更新入口
  - 可以即时改写当前 thread 的 future eligibility
  - 但它改的是“后续是否继续参与 memory 生成”，不是 turn 级全量热替换

另外必须注意一个边界：

- memory 数据根目录是全局 `CODEX_HOME/memories`
- 不是按 thread 隔离的独立 memory 空间
- 因此“不同 thread 可开关 memory”不等于“每个 thread 有自己的 memory 仓库”

### 3.2 `skills`

上游 TUI 已有 `/skills` 命令，职责是：

- 列出技能
- 启用 / 禁用技能

源码事实：

- slash 命令已注册，描述为“use skills to improve how Codex performs specific tasks”
- `/skills` 实际打开的是技能菜单，不是 thread 私有设置页
- 技能来源会按作用域自动发现：
  - 仓库 `.agents/skills`
  - 用户 `$HOME/.agents/skills`
  - 系统缓存 / 系统目录
- turn 构建时会重新求 effective skills
- `skills/config/write` 后 app-server 会清 `skills/plugins` cache

结论：

- `skills` 是 **配置 + 目录作用域能力面**
- 不是 thread 私有状态
- 不需要 backend 重启
- 通常下一轮 turn 即可生效

### 3.3 `plugins`

上游 TUI 已有 `/plugins` 命令，职责远重于 `skills`：

- 浏览 marketplace / installed plugin
- 查看插件详情
- install / uninstall
- 已安装插件 enable / disable
- 可能牵连 plugin skill、MCP、apps、auth

源码事实：

- TUI 中 `/plugins` 是完整的插件浏览器
- app-server 协议面包括：
  - `plugin/list`
  - `plugin/read`
  - `plugin/install`
  - `plugin/uninstall`
  - `marketplace/add/remove/upgrade`
- 已安装插件还存在单独的 enable / disable 写配置路径
- plugin 变化后会清 plugin / skill cache
- 若存在已加载 thread，还会触发 best-effort MCP refresh
- turn 构建时按当前 effective plugins 重新注入能力面

结论：

- `plugins` 是 **配置 + marketplace + 外部能力接入面**
- 比 `skills` 副作用更大
- 不需要 backend 重启
- 但“下一轮就完全可用”不总是等价于“安装动作已经完全结束”，因为还可能牵涉 auth / apps / MCP

### 3.4 `subagents / agents`

上游 TUI 中 `/agent` 和 `/subagents` 的职责，不是“手工创建一个子代理”，而是：

- 打开 agent picker
- 查看 / 切换 active agent thread

真正执行多代理的是底层工具：

- `spawn_agent`
- `wait_agent`
- `close_agent`
- `list_agents`

源码事实：

- slash 命令描述是“switch the active agent thread”
- `/agent` 与 `/subagents` 都是打开 `OpenAgentPicker`
- 上游对 `spawn_agent` 的工具合同明确要求：
  - 只有用户明确要求 delegation / subagent / parallel work 时才可使用

结论：

- `subagents` 首先是 **运行时能力**
- TUI 命令层主要解决“人如何查看 / 切换 agent thread”
- 飞书若要接入，重点不该放在“给用户手工 spawn 按钮”，而该放在“查看 agent tree / 状态 / 最终结果”

### 3.5 `compact`

上游 TUI 已有 `/compact` 命令，描述是：

- summarize conversation to prevent hitting the context limit

源码事实：

- app-server 已提供 `thread/compact/start`
- compaction 是 thread 内显式操作
- 它会替换 / 压缩当前 thread 的历史，不是全局配置
- compaction 期间同 turn steering 会被拒绝

结论：

- `compact` 是 **thread 级显式操作**
- 不是配置面
- 很适合飞书接入

## 4. 是否建议接入飞书

### 4.1 `memory / memories`

建议接入，但不要机械照搬上游 TUI 的两个布尔旋钮。

原因：

- 上游两个旋钮本身分属不同状态层：
  - `use_memories` 更接近 session/config 侧
  - `generate_memories` 则部分落在 thread metadata
- 若飞书直接暴露两个布尔值，用户需要理解：
  - 为什么一个改了当前 thread 不立即生效
  - 为什么另一个又会影响当前 thread
  - 为什么两者都叫“memory 设置”，却不是同一种生效方式
- 这与当前仓库的设计偏好冲突：
  - 更清晰
  - 更少歧义
  - 更易维护

因此，飞书侧更合适的产品合同是：定义 **thread-wise 的单一 memory mode**。

推荐枚举：

- `off`
- `read`
- `read_write`

映射关系：

- `off`
  - `use_memories = false`
  - `generate_memories = false`
  - `memory_mode = disabled`
- `read`
  - `use_memories = true`
  - `generate_memories = false`
  - `memory_mode = disabled`
- `read_write`
  - `use_memories = true`
  - `generate_memories = true`
  - `memory_mode = enabled`

刻意不暴露的组合：

- `generate = true` 且 `use = false`

原因：

- 上游虽允许，但非常偏门
- 会显著增加解释成本
- 对飞书主流程没有足够收益

正式生效合同建议写死为：

- memory mode 是 **thread-wise**
- 改动后对当前 loaded thread 不承诺热更新
- 正式路径是：
  - 保存 thread-wise memory mode
  - 必要时 `reset-backend`
  - 再恢复当前 thread
- 这样能保证：
  - 不同 thread 有不同 memory 设置
  - 用户只需理解一种生效路径
  - 合同比“一个热更新、一个不热更新”更一致

与上游的关系应明确写成：

- 这不是 1:1 复刻上游 TUI 设置页
- 这是本项目基于上游能力面重新定义的飞书产品合同
- 目的是降低用户心智负担，而不是保留上游历史形状
### 4.2 建议优先接入

#### `skills`

原因：

- 合同清楚
- 作用域明确
- 无需重启 backend
- 飞书侧比 TUI 更缺“可见性”

飞书价值不在“让技能可用”，而在：

- 展示当前目录可见 skills
- 展示作用域
- enable / disable

#### `compact`

原因：

- 语义简单
- 是 thread 内显式动作
- 非全局配置
- 很适合飞书线程操作面

### 4.3 建议谨慎接入

#### `plugins`

建议接入，但第一阶段只做轻量面：

- 列表
- 详情
- 已安装插件的 enable / disable

不建议第一阶段就接：

- install / uninstall
- marketplace 管理
- plugin share
- auth 驱动流程

原因：

- 状态层更重
- 副作用更大
- 容易把普通飞书导航页拖成半个插件商店

### 4.4 建议暂不做写入口

#### `subagents / agents`

建议第一阶段只考虑：

- 查看当前 agent tree
- 查看状态
- 查看最终结果

不建议第一阶段做：

- 手工 spawn subagent
- 把子代理过程直接并入主执行卡实时 patch

原因：

- 主流程卡片会显著复杂化
- 多 agent 状态树在飞书卡片中实时维护成本高
- 自然语言本来就已能触发 `spawn_agent`

## 5. 飞书信息架构建议

### 5.1 主流程

`compact` 放到“线程”面，而不是高级功能页。

原因：

- 它是 thread 级操作
- 与 `/new`、`/resume`、`/archive` 同属线程动作

`memory mode` 若后续接入，也应放到“线程”面，而不是“当前会话”或“高级功能”页。

原因：

- 它应是 thread-wise
- 与 `profile` 更接近
- 不属于 binding-wise runtime setting

### 5.2 高级功能页

新增一个单独的“Codex 高级功能”页，第一阶段只考虑：

- `skills`
- `plugins`

可选预留：

- `agents`

原因：

- 这些能力都不是当前飞书 binding 私有状态
- 放进现有“当前会话 / 群聊 / 线程 / 运行时”主流程会混淆状态层

### 5.3 `memory mode` 页的推荐形状

若后续接入飞书，不建议做两个独立 toggle，而建议做单选页：

- `off`
- `read`
- `read_write`

并在提交时明确提示：

- 该设置保存到当前 thread
- 当前 thread 若已 loaded，需重置 backend 后重新恢复才会完整生效

不建议在第一页解释过多上游实现细节，只需保留用户真正需要知道的结果语义。

### 5.4 `agents` 页的推荐形状

若后续接入，不建议为每个子代理生成一套新的“执行卡 + 终态卡”。

更建议做成一个按需打开的查看页，展示：

- agent 名称 / 路径
- 状态
- 最近任务
- 最终结果摘要

这样能保持：

- 主执行卡简单
- 子代理观察面独立
- 后续实现成本可控

## 6. 当前建议的收敛结果

当前尚值得继续纳入飞书设计面的候选有四个：

1. `skills`
2. `plugins`（先只读 + 已安装项启停）
3. `agents` 查看页
4. `compact`

其中推荐优先级：

1. `compact`
2. `skills`
3. `plugins`
4. `agents`

## 7. 暂不纳入本文的项目

本文明确不处理：

- `hooks`
- `mcp`
- `apps`
- 其它 TUI 本地 UI 专属命令

这些项目后续如需接入飞书，应另行分析，不与本文混写。

## 8. 关键源码参考

- `~/llm/codex/codex-rs/tui/src/slash_command.rs`
- `~/llm/codex/codex-rs/tui/src/chatwidget/slash_dispatch.rs`
- `~/llm/codex/codex-rs/tui/src/chatwidget/skills.rs`
- `~/llm/codex/codex-rs/core-skills/src/loader.rs`
- `~/llm/codex/codex-rs/app-server/src/request_processors/catalog_processor.rs`
- `~/llm/codex/codex-rs/core/src/session/turn_context.rs`
- `~/llm/codex/codex-rs/tui/src/chatwidget/plugins.rs`
- `~/llm/codex/codex-rs/app-server-protocol/src/protocol/v2/plugin.rs`
- `~/llm/codex/codex-rs/app-server/src/request_processors/plugins.rs`
- `~/llm/codex/codex-rs/core/src/tools/handlers/multi_agents_spec.rs`
- `~/llm/codex/codex-rs/app-server-protocol/src/protocol/common.rs`
