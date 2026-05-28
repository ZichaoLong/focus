# 运行时 permissions profile 迁移计划 — 2026-05-28

Status: working material under `docs/_work/`. Not a repository fact.

本文记录把 `feishu-codex` 的飞书侧 runtime settings，从当前的 legacy
`approval_policy + sandbox + permissions preset` 产品层，迁移到与上游
app-server 当前 canonical path 更一致的实现形态时，必须遵守的约束、阶段边界与验收标准。

本文不是正式合同。它的作用是：

- 固定本轮改造的边界，避免中途把“上游对齐”“产品重做”“帮助导航调整”混成一件事
- 明确哪些改动属于阶段 A，哪些属于阶段 B
- 明确哪些现有合同在阶段 A 不能动，哪些在阶段 B 可以成体系升级

本文**不要求实现过程必须按阶段 A 再阶段 B 的顺序提交**。

它约束的是：

- 最终交付物允许处于哪些状态
- 一旦决定把产品合同一起迁移，哪些部分必须成体系收口
- 哪些中间态不能作为最终结果保留下来

---

## 1. 当前仓库事实

### 1.1 当前飞书侧 runtime settings 是 binding-wise persisted state

当前 binding 级持久化状态里，正式字段包括：

- `approval_policy`
- `sandbox`
- `collaboration_mode`
- `model`
- `reasoning_effort`

相关实现：

- `bot/binding_runtime_manager.py`
- `bot/stores/chat_binding_store.py`
- `bot/runtime_view.py`

这意味着：

- `sandbox` 不是仅存在于 adapter 的旧参数
- 它已经是当前 runtime state schema 的一部分
- status / preflight / 管理视图也都把它当成一等读侧字段

### 1.2 当前 `/permissions` 是产品层组合预设，不是独立 persisted 字段

当前飞书侧的命令与卡片控制面是：

- `/approval`
- `/sandbox`
- `/permissions`

其中：

- `/approval` 直接修改 `approval_policy`
- `/sandbox` 直接修改 `sandbox`
- `/permissions` 先解析为一个预设，再展开成 `approval_policy + sandbox`

当前默认预设为：

- `read-only` -> `on-request + read-only`
- `default` -> `on-request + workspace-write`
- `full-access` -> `never + danger-full-access`

所以，当前仓库里：

- `permissions` 不是 runtime state schema 的独立事实字段
- `permissions` 是产品控制面上的组合入口

### 1.3 当前合同已经把这套三入口并存写成正式行为

当前正式合同已经明确：

- `/permissions`：同时设置审批策略与沙箱策略
- `/approval`：设置审批策略
- `/sandbox`：设置沙箱策略

并且这些入口都可通过飞书 help / workbench 到达。

因此，若直接把 `/permissions` 改成“只改独立 permission profile id”，这将不是实现清理，而是正式产品合同变更。

### 1.4 adapter 层已经部分转向上游 canonical path

当前 app-server adapter 已经会优先发送：

- `permissions`

并在旧后端不支持时回退到：

- `sandbox`
- `sandboxPolicy`

因此当前仓库实际上处于一种“上下分叉”状态：

- **产品层 / 持久化层** 仍是 `approval_policy + sandbox`
- **上游注入层** 已开始优先走 `permissions`

### 1.5 当前 runtime settings 的合同是 frontend-owned、binding-wise、next-turn 注入

这批设置当前不属于：

- thread-wise next-load state
- 所有前端共享的一份 thread 级真相

它们属于：

- frontend-owned runtime settings
- binding-wise persisted settings
- 在 `thread/start` / `turn/start` 时由当前飞书 binding 注入

这点在现有合同中已经成立，后续改造不应意外破坏。

---

## 2. 上游现状与目标对齐

### 2.1 上游当前有三个不同层次的概念

1. `approvalPolicy`
- 仍是 thread/start / thread/resume / turn/start 的正式 override 字段

2. legacy `sandbox` / `sandboxPolicy`
- 仍兼容
- 但已不是推荐主路径

3. experimental `permissions`
- 当前 canonical 的权限基线入口
- 它传的是 **permission profile id**
- 不是完整 config profile

### 2.2 上游内置 permission profile id

当前至少有以下 built-in id：

- `:read-only`
- `:workspace`
- `:danger-full-access`

本轮改造第一阶段仅允许依赖这三个 built-in id，不要求同时把自定义
`[permissions.<id>]` 产品化。

---

## 3. 本轮目标

本轮目标分两阶段。

### 3.1 阶段 A：上游注入路径与内部桥接层收敛

目标：

- 保持当前正式用户合同基本不变
- 保持当前命令面与状态摘要基本不变
- 让本项目发送到上游 app-server 的权限基线表达，稳定切到 canonical `permissions`
- 把 `sandbox` 三态与上游 built-in permission profile id 建立显式桥接

这一阶段结束后，项目外观上仍然允许用户理解为：

- `/permissions` 是组合预设
- `/approval` 与 `/sandbox` 是两个独立旋钮

但实现上：

- 不再依赖 legacy `sandbox` / `sandboxPolicy` 作为主路径

### 3.2 阶段 B：产品层与持久化 schema 正式迁移

目标：

- 把飞书侧 runtime settings 的权限基线，从 `sandbox` 语义正式迁移到
  `permissions_profile_id`
- 把 `/permissions` 从“组合预设”升级为“独立权限基线入口”
- 重新界定 `/approval`、`/permissions`、`/sandbox` 的关系
- 更新状态摘要、help/workbench、合同文档与持久化 schema

这一阶段结束后，项目语义应变为：

- `approval_policy`：审批边界
- `permissions_profile_id`：权限基线
- `sandbox`：不再作为正式用户面 persisted 字段

---

## 4. 强约束

### 4.1 阶段 A 不得改动的内容

阶段 A 期间，不得：

- 改变 `/permissions` 现有外部语义
- 删除 `/approval` 或 `/sandbox`
- 让 `/status` / `/preflight` / runtime admin 摘要突然失去现有三层展示
- 调整 help/workbench 导航层级来“顺带完成设计清理”
- 把持久化 schema 直接改成 `permissions_profile_id` 并删除 `sandbox`

阶段 A 的任务是：

- **只改注入路径与内部桥接**

### 4.2 阶段 B 必须整体提交，不接受“半迁移”

一旦开始阶段 B，必须成体系完成：

- persisted state schema
- runtime read model
- settings domain
- cards
- status / preflight / runtime admin 摘要
- help / commands / README 相关运行时设置描述
- contracts 文档

不接受以下中间态长期存在：

- 持久化已经改成 `permissions_profile_id`，但 `/permissions` 仍宣称是组合预设
- UI 已删除 `/sandbox`，但 status 摘要和合同文档仍以 `sandbox` 为一等字段
- adapter 已只收 `permissions`，但上层仍没有一套稳定的 `permissions_profile_id` 事实源

### 4.3 本轮不扩展到自定义 permission profile 用户面

本轮阶段 B 不要求：

- 暴露 `permissionProfile/list`
- 允许用户直接输入任意 profile id
- 支持管理员在飞书侧创建或编辑自定义 `[permissions.<id>]`

阶段 B 的权限基线用户面，仅覆盖：

- `:read-only`
- `:workspace`
- `:danger-full-access`

### 4.4 本轮不同时解决 thread/resume 注入语义争议

当前本轮不要求同时解决：

- binding-wise settings 在 `thread/resume` 是否注入
- 注入后是否覆盖 loaded thread / sticky settings
- 与 `/goal resume` 的交互冲突

本轮聚焦：

- 当前飞书 binding 在 `thread/start` / `turn/start` 的注入形态

---

## 5. 阶段 A 方案

### 5.1 用户合同保持不变

阶段 A 对外仍保持：

- `/permissions [read-only|default|full-access]`
- `/approval [untrusted|on-request|never]`
- `/sandbox [read-only|workspace-write|danger-full-access]`

保持：

- `/permissions` 仍是组合预设
- `/approval`、`/sandbox` 仍是独立入口
- status / preflight / admin 摘要仍展示：
  - 权限预设
  - 审批策略
  - 沙箱策略

### 5.2 内部桥接关系

阶段 A 内部建立明确映射：

- `read-only` -> `:read-only`
- `workspace-write` -> `:workspace`
- `danger-full-access` -> `:danger-full-access`

适用范围：

- `thread/start`
- `turn/start`

如需保留旧后端兼容，可在阶段 A 内继续保留 fallback；若项目决定不再兼容旧后端，也可在阶段 A 中删除 fallback，但这不应改变用户面合同。

### 5.3 阶段 A 结束时的系统状态

阶段 A 完成后，项目应处于：

- 产品合同仍是旧模型
- 上游注入主路径已是新模型
- `sandbox` 在本项目内部仍是正式 persisted 字段
- `permissions` 仍不是独立 persisted 字段

这是一个**可接受的过渡稳态**。

---

## 6. 阶段 B 方案

### 6.1 新的正式模型

阶段 B 完成后，飞书侧 runtime settings 的正式模型改为：

- `approval_policy`
- `permissions_profile_id`
- `collaboration_mode`
- `model`
- `reasoning_effort`

删除正式 persisted 字段：

- `sandbox`

### 6.2 新的用户面

阶段 B 后：

- `/permissions`：设置权限基线
- `/approval`：设置审批策略
- `/sandbox`：不再作为正式用户入口

此时 `/permissions` 的值建议直接与 built-in permission profile 对齐，但展示名仍可使用稳定的人类可读标签。

推荐展示映射：

- `只读` <-> `:read-only`
- `工作区写` <-> `:workspace`
- `完全访问` <-> `:danger-full-access`

是否继续保留英文参数名，由实现阶段决定；但最终合同中，`/permissions`
不应再定义为“同时修改审批与沙箱的组合预设”。

### 6.3 新的状态摘要

阶段 B 后，status / preflight / runtime admin 摘要应改为展示：

- 权限基线
- 审批策略
- 协作模式
- model override
- effort override

删除展示：

- 沙箱策略
- 旧权限预设（若其定义依赖 `approval + sandbox`）

### 6.4 新的合同表述

阶段 B 后，正式合同必须同步更新为：

- `permissions` 是独立 runtime setting
- 它对应上游 permission profile id
- 它不是完整 config profile
- `approval_policy` 仍是独立 runtime setting
- `sandbox` 不再是飞书侧正式 persisted setting

---

## 7. 代码改造边界

### 7.1 阶段 A 必须触达的区域

- adapter 注入链路
- runtime settings 到 adapter 的桥接逻辑
- 必要的测试

### 7.2 阶段 A 明确不应主动改的区域

- `binding_runtime_manager` persisted schema
- `chat_binding_store` schema
- `runtime_view` 中的 `RuntimeSettingsView.sandbox`
- `/permissions` 卡片与命令的表面语义
- help/workbench 导航结构
- 正式合同文案

### 7.3 阶段 B 必须整体触达的区域

- `binding_runtime_manager`
- `chat_binding_store`
- `runtime_view`
- `codex_settings_domain`
- `cards`
- `runtime_admin_controller`
- `shared_command_surface`
- `codex_help_domain`
- `README`
- `docs/contracts/*` 相关运行时设置文档

---

## 8. 验收标准

### 8.1 阶段 A 验收

必须满足：

1. 用户在飞书侧继续看到当前三入口与当前状态摘要模型
2. `thread/start` / `turn/start` 的主路径不再依赖 legacy `sandbox` 语义
3. `read-only` / `workspace-write` / `danger-full-access` 到 built-in
   permission profile id 的映射是显式、稳定、可测试的
4. 不引入 help/workbench/合同层的静默语义漂移

### 8.2 阶段 B 验收

必须满足：

1. persisted runtime state 已正式迁成 `approval_policy + permissions_profile_id`
2. `/permissions` 已是独立权限基线入口
3. `/sandbox` 不再是正式控制面
4. status / preflight / admin 摘要与新模型一致
5. 正式合同与实现一致，不再写“`/permissions` 展开成 `approval_policy + sandbox`”
6. 文档、help、卡片与命令矩阵同步完成

---

## 9. 本轮目标设定建议

如果本轮 goal 只是“对齐上游 canonical path，但不承诺同时改产品合同”，
则最终允许的完成态是：

- 达到本文第 8.1 节阶段 A 验收标准
- 仍保留当前 `/permissions`、`/approval`、`/sandbox` 三入口与旧合同

如果本轮 goal 明确包含“连产品合同也一并完成迁移”，则最终必须满足：

- 达到本文第 8.2 节阶段 B 验收标准
- 不得把任何阶段 A 的桥接中间态当作最终交付结果保留

也就是说：

- **goal 可以只描述目标，不必约束实施过程**
- **但一旦目标包含产品合同迁移，最终结果必须受本文的阶段 B 约束**
