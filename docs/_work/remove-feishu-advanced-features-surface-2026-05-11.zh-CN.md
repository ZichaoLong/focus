# Feishu 侧 `skills / plugins / MCP` 产品面移除清单与执行计划

日期：2026-05-11

## 1. 结论

建议把 `feishu-codex` 中这三类“高级能力”的**正式产品面**收回：

- `/skills`
- `/plugins`
- 任何面向普通飞书用户的 MCP 观察或管理入口

目标不是“禁用 upstream 的这些机制”，而是：

- 不再由 `feishu-codex` 自己观察它们
- 不再由 `feishu-codex` 自己管理它们
- 不再由 `feishu-codex` 自己承诺它们与 upstream runtime 的一致性

本项目应回到更清晰的角色：

- `thread / binding / runtime` 前端
- `resume / attach / load / unload / reset` 交互壳
- `thread-wise next-load state` 管理者

而不是 upstream advanced features 的二次控制台。

## 2. 本次移除的边界

### 2.1 要移除的，是 Feishu 产品面

这里要移除的是：

- 飞书 slash 命令入口
- 帮助页、导航、卡片
- adapter 暴露的 `skills / plugins` 观察与开关接口
- 对这些入口负责的合同文档与测试

### 2.2 不要误删 upstream 原生机制

这里**不是**：

- 删除用户自己的 skill 文件
- 删除 repo 自带 `.agents/skills`
- 禁掉 upstream 自己的 skill discovery
- 禁掉 upstream 自己按配置加载的 plugin / MCP
- 破坏普通 `turn/start` 主链路

### 2.3 `manage_cli skill` 不属于本次移除范围

`feishu-codex skill install/uninstall` 的职责是：

- 把 repo 自带的工作区 skill 资产装到当前目录 `.agents/skills`

它是一个**本地资产安装器**，不是飞书里的 `/skills` 管理面。

因此应保留：

- [bot/manage_cli.py](/home/zlong/llm/feishu-codex/bot/manage_cli.py)
- [/home/zlong/llm/feishu-codex/.agents/skills](/home/zlong/llm/feishu-codex/.agents/skills)

## 3. 现状判断

### 3.1 `skills`

当前飞书侧 `/skills` 是一套独立产品面：

- slash 路由见 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py)
- 帮助与导航见 [bot/codex_help_domain.py](/home/zlong/llm/feishu-codex/bot/codex_help_domain.py)
- 领域逻辑见 [bot/codex_advanced_features_domain.py](/home/zlong/llm/feishu-codex/bot/codex_advanced_features_domain.py)
- adapter 接口与解析见 [bot/adapters/base.py](/home/zlong/llm/feishu-codex/bot/adapters/base.py)、[bot/adapters/codex_app_server.py](/home/zlong/llm/feishu-codex/bot/adapters/codex_app_server.py)

但普通飞书 prompt 链路当前并不会主动构造结构化 `skill` input item。
它主要只发：

- `text`
- `localImage`

因此删除 `/skills` 不会砍断一条当前已稳定依赖的结构化 skill 调用链。

### 3.2 `plugins`

当前飞书侧 `/plugins` 同样是一套独立产品面：

- slash 路由与 action 路由都在 [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py)
- 领域逻辑同样集中在 [bot/codex_advanced_features_domain.py](/home/zlong/llm/feishu-codex/bot/codex_advanced_features_domain.py)
- adapter 暴露了 `plugin/list`、`plugin/read`、`config/value/write`

但普通飞书 prompt 链路当前也没有发送结构化 `mention` item。
因此删除 `/plugins` 更像是移除一个“观察/切换面”，而不是删除一条当前成熟可用的飞书 plugin 调用链。

### 3.3 `MCP`

当前没有正式的 Feishu MCP 管理面。
与 MCP 直接相关的用户可见行为，主要只剩一条 fail-close 兼容：

- 收到 `mcpServer/elicitation/request` 时，飞书侧自动取消

对应文件：

- [bot/interaction_request_controller.py](/home/zlong/llm/feishu-codex/bot/interaction_request_controller.py)
- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py)

因此所谓“MCP 移除”，不应理解为删除所有 `mcp` 字样代码，而应理解为：

- 不新增 MCP 产品面
- 保留最小协议兼容

## 4. 可安全删除清单

### 4.1 用户命令与交互入口

应删除：

- `"/skills"` 命令路由
- `"/plugins"` 命令路由
- `set_skill_enabled` action 路由
- `show_plugins_overview` action 路由
- `show_plugin_detail` action 路由
- `set_plugin_enabled` action 路由

主要文件：

- [bot/codex_handler.py](/home/zlong/llm/feishu-codex/bot/codex_handler.py)

### 4.2 领域层

应整体删除：

- [bot/codex_advanced_features_domain.py](/home/zlong/llm/feishu-codex/bot/codex_advanced_features_domain.py)

这是本次移除的中心文件。其职责几乎完全就是：

- `/skills` 列表与启停卡
- `/plugins` 列表、详情与启停卡

### 4.3 命令面元数据

应删除：

- `shared_command_surface` 中的 `skills`
- `shared_command_surface` 中的 `plugins`

主要文件：

- [bot/shared_command_surface.py](/home/zlong/llm/feishu-codex/bot/shared_command_surface.py)

### 4.4 adapter 抽象与 app-server 适配层

应删除的抽象方法：

- `list_skills`
- `set_skill_enabled`
- `list_plugins`
- `read_plugin`
- `set_plugin_enabled`

应删除的数据结构：

- `SkillSummary`
- `SkillsSnapshot`
- `PluginSummary`
- `PluginMarketplaceSummary`
- `PluginCatalog`
- `PluginDetailSummary`

主要文件：

- [bot/adapters/base.py](/home/zlong/llm/feishu-codex/bot/adapters/base.py)
- [bot/adapters/codex_app_server.py](/home/zlong/llm/feishu-codex/bot/adapters/codex_app_server.py)

`codex_app_server.py` 中可一并删除：

- `skills/list` 适配
- `skills/config/write` 适配
- `plugin/list` 适配
- `plugin/read` 适配
- `plugins.<id>.enabled` 写入适配
- 对应结果解析 helper

## 5. 必须保留的兼容壳

### 5.1 普通 turn 主链路

必须保留：

- `thread/start`
- `thread/resume`
- `turn/start`
- 普通文本与图片输入链路

这些是本项目主干，不属于 advanced features。

### 5.2 MCP elicitation fail-close

必须保留：

- [bot/interaction_request_controller.py](/home/zlong/llm/feishu-codex/bot/interaction_request_controller.py) 中对 `mcpServer/elicitation/request` 的取消逻辑
- [bot/fcodex_proxy.py](/home/zlong/llm/feishu-codex/bot/fcodex_proxy.py) 中把它视为 interactive server request 的处理

原因：

- 如果 MCP 在 turn 中真的发起 elicitation，而客户端既不处理也不取消，行为会更差
- 这里属于运行时协议兼容，不属于产品面

### 5.3 本地受管 skills 资产

必须保留：

- repo 内 `.agents/skills`
- `feishu-codex skill install`
- `feishu-codex skill uninstall`

原因：

- 这是本地资产分发能力
- 它不要求飞书侧观察或管理 runtime skills 状态

## 6. 文档处理清单

### 6.1 应更新或移除的正式合同

应移除或归档：

- [docs/contracts/feishu-advanced-features.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-advanced-features.md)
- [docs/contracts/feishu-advanced-features.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-advanced-features.zh-CN.md)

建议：

- 不再保留为“当前正式合同”
- 如需留历史，可移到 `docs/archive/`

应更新：

- [docs/contracts/feishu-help-navigation.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-help-navigation.md)
- [docs/contracts/feishu-help-navigation.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-help-navigation.zh-CN.md)
- [docs/contracts/feishu-command-matrix.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-command-matrix.md)
- [docs/contracts/feishu-command-matrix.zh-CN.md](/home/zlong/llm/feishu-codex/docs/contracts/feishu-command-matrix.zh-CN.md)
- [docs/doc-index.md](/home/zlong/llm/feishu-codex/docs/doc-index.md)
- [docs/doc-index.zh-CN.md](/home/zlong/llm/feishu-codex/docs/doc-index.zh-CN.md)

### 6.2 不应误删的文档

不应因为关键字命中就删除：

- `docs/_work/` 下历史调研
- `docs/contracts/thread-next-load-settings-semantics*`
- `docs/decisions/feishu-output-images.zh-CN.md`

这些文档提到 `skills / plugins / mcp`，但不等于它们仍是当前飞书正式产品面。

## 7. 测试处理清单

### 7.1 应删除或改写的测试

应删除：

- [tests/test_codex_handler.py](/home/zlong/llm/feishu-codex/tests/test_codex_handler.py) 中 `/skills`、`/plugins`、`advanced` 帮助页相关测试
- [tests/test_codex_app_server.py](/home/zlong/llm/feishu-codex/tests/test_codex_app_server.py) 中 `skills/plugin` adapter 方法测试

并同步简化：

- fake adapter 中的 `skills_snapshots`
- fake adapter 中的 `plugin_catalogs`
- fake adapter 中的 `plugin_details`
- 以及相关 helper

### 7.2 应保留的测试

应保留：

- 普通 prompt / turn 启动链路测试
- `/compact`、thread、runtime、profile、memory 等核心面测试
- `manage_cli skill install/uninstall` 测试
- `mcpServer/elicitation/request` fail-close 测试

## 8. 执行计划

### 阶段 1：先收口产品合同

修改目标：

- 移除 `/skills`、`/plugins`
- 移除帮助页里的 `advanced`
- 更新 command matrix / help navigation / doc index
- 明确文档边界：
  - 飞书侧不再管理 `skills / plugins / MCP`
  - 这些能力若存在，由 upstream 自己负责

完成标准：

- 用户已经无法在飞书帮助和命令面看到这些入口
- 正式文档不再宣称支持这些能力

### 阶段 2：删除领域逻辑与 adapter 代码

修改目标：

- 删除 `codex_advanced_features_domain.py`
- 删除 `codex_handler.py` 中相关初始化、命令路由、action 路由
- 删除 adapter 抽象与 `codex_app_server.py` 中相关实现

完成标准：

- repo 中不再存在任何飞书侧 `/skills`、`/plugins` 主路径代码
- 不影响普通 thread / turn 主链路

### 阶段 3：清理测试与死代码

修改目标：

- 删掉不再需要的 fake adapter 状态与测试
- 清理只为 advanced features 服务的类型

完成标准：

- 没有悬空 import
- 没有保留只为已删除功能服务的数据结构

### 阶段 4：回归验证

建议至少跑：

```bash
/home/zlong/anaconda3/bin/python -m pytest \
  /home/zlong/llm/feishu-codex/tests/test_codex_handler.py \
  /home/zlong/llm/feishu-codex/tests/test_codex_app_server.py \
  /home/zlong/llm/feishu-codex/tests/test_manage_cli.py
```

如阶段 1 已删掉相应测试，可改成剩余相关测试文件。

建议额外人工验证：

- `/help`
- `/help thread`
- `/help runtime`
- `/compact`
- 普通文本对话
- 图片输入对话
- `mcpServer/elicitation/request` 的自动取消

## 9. 变更后的预期行为

收口完成后，系统应表现为：

- 飞书里没有 `/skills`
- 飞书里没有 `/plugins`
- 飞书帮助里没有 `advanced` 页
- 飞书侧不再声称自己能观察或控制 runtime `skills / plugins / MCP`
- upstream 若仍自动发现 user/repo skills，那是 upstream 自己的行为
- repo 自带 `.agents/skills` 仍可通过本地 CLI 安装供 upstream 使用
- MCP 若在运行时发起 elicitation，请求仍被明确 cancel，而不是悬空

## 10. 推荐实施顺序

推荐按下面顺序做，而不是一次性大删：

1. 先删帮助与命令入口，更新合同文档
2. 再删 `codex_advanced_features_domain.py`
3. 再删 adapter 层 `skills/plugins` 接口与类型
4. 最后清理测试和残余引用

原因：

- 先收口产品边界，最容易看清哪些代码已死
- 可以避免一开始把“资产安装器 skill”与“飞书 `/skills` 管理面”混删
- 可以避免误删 `mcpServer/elicitation/request` 这种必须保留的兼容壳
