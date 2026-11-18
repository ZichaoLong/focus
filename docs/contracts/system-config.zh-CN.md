# `system.yaml` 准入合同

文档角色：中文规范源。英文同步副本：`docs/contracts/system-config.md`。

## 目的

`system.yaml` 保存一个 Focus 实例连接飞书所需的应用身份，以及该实例的管理员、
触发身份、网络和群历史回捞设置。这些字段位于安全敏感的准入边界：把
`"false"` 当成布尔值、把字符串列表逐字符展开，或在列表中静默跳过坏项，都可能
改变谁能触发机器人、记录哪些敏感信息或服务会等待多久。

本文把该文件定义成一个明确、fail-closed 的实例静态配置边界。它不定义
`codex.yaml`、飞书 binding 持久化状态、active main-turn lease，也不定义
上游 `~/.codex/config.toml`。

## 前端启用与生命周期

`focusd` 始终持有一个必需的 Codex backend；飞书与 Web 是互不依赖的可选前端。
`system.yaml.feishu_enabled` 缺省为 `false`；`codex.yaml.web_enabled` 缺省为 `true`，安装模板与各自缺省值一致。
缺少配置文件或 enable 字段时使用各自缺省值；显式 `false` 关闭对应前端，升级不覆盖已有显式值。
已有凭据不会隐式启用飞书，不提供旧飞书配置自动启用兼容。
只有 `feishu_enabled: true` 时，`app_id` 与 `app_secret` 才必须非空。配置值仍按完整 schema 严格校验。

| 飞书 | Web | 运行模式 |
| --- | --- | --- |
| 关闭 | 关闭 | 核心、focusctl、focus/fcodex |
| 开启 | 关闭 | 核心与飞书 |
| 关闭 | 开启 | 核心与 Web，无需飞书凭据 |
| 开启 | 开启 | 两个前端共享同一核心 |

切换开关需要重启实例，不做热插拔，也不更改安装包依赖集合。关闭飞书不导入 Lark SDK、不构造机器人与命令展示面，
不获取应用连接 lease，不启动飞书连接、目的地检测或输出/recovery worker。历史 binding 只作为本地记录读取和清理，
不恢复 subscriber、writer、FIFO 或网络推送；重新启用仍从 detached bookmark 开始，不能重放旧队列。

启用时，`FeishuTransport` 独占 SDK loop/thread，核心 ACTIVE 后才开放飞书连接；连接故障通过
`service/status.operator_status.feishu` 的 `enabled`、`state`、`error` 独立显示，不关闭仍可用的 Web/本地管理面。
停止时先关闭核心 ingress 并等待已准入 callback，再停止/join 飞书 producer，最后释放机器 authority。
未确认 producer 退出时保留应用与 service lease。SDK endpoint discovery 使用配置的 HTTP timeout。


## 权威源与投影

`bot.system_config.SystemConfig` 是 `system.yaml` 可接受键清单、默认值、类型、范围和
规范化规则的唯一权威事实源。

- `config/system.yaml.example` 是面向源码安装的可读投影；
  `bot/install_template_data/system.yaml.example` 是安装包投影。测试要求两份内容相同，
  且两者记录的键清单与 schema 完全相等。
- daemon 入口先把整份文件解析为 `SystemConfig`，之后才按开关创建 `CodexBot`。
- `FeishuBot` 只消费经过同一 schema 解析的类型值，不再自行调用 `str()`、`float()`、
  `int()` 或静默过滤列表项。
- runtime admin 读取飞书 HTTP timeout 时也校验完整文件；坏值不会回落默认值后继续。

新增设置必须同时修改 `SystemConfig` 字段/parser、两份 example 投影、合同与 schema
测试。在 consumer 中新增一处 `dict.get()` 不构成正式支持。

## 正式字段

| 字段 | 类型与范围 | 缺省语义 |
| --- | --- | --- |
| `feishu_enabled` | YAML 布尔值 | `false`；仅显式 `true` 启用 |
| `app_id` | 去除首尾空白的字符串 | 空字符串；启用飞书时必须非空 |
| `app_secret` | 去除首尾空白的字符串 | 空字符串；启用飞书时必须非空 |
| `request_timeout_seconds` | 有限数字，严格大于 `0` | `5.0` 秒 |
| `feishu_ws_proxy` | 封闭枚举 `env` / `disabled`，大小写规范化 | `env` |
| `admin_open_ids` | 不重复的非空字符串列表 | 空列表 |
| `bot_open_id` | 字符串；空字符串表示尚未配置 | 空字符串 |
| `trigger_open_ids` | 不重复的非空字符串列表 | 空列表 |
| `group_history_fetch_limit` | 大于等于 `0` 的整数 | `50`；`0` 禁用回捞 |
| `group_history_fetch_lookback_seconds` | 大于等于 `0` 的整数 | `86400`；`0` 禁用回捞 |
| `debug_raw_card_ingress` | YAML 布尔值 | `false` |

`debug_raw_card_ingress` 会记录可能包含用户输入和身份信息的原始卡片回调，只用于短期
诊断，因此默认必须保持关闭。

## 准入规则

- 文档顶层必须是字符串键的 mapping。任何层级的重复 mapping key、未知顶层键和
  显式 null 一律拒绝；重复键不能以“最后一个值生效”解释。
- 字符串、布尔值、整数、数字和字符串列表是不同类型。字符串数字不会转成数字，
  布尔值也不会按 Python 的整数子类解释。
- 数字必须有限并满足上表范围。`NaN`、无穷、非正 timeout 和负数历史窗口均拒绝。
- open-id 字段必须是 YAML list；每项去除首尾空白后必须非空且唯一。标量、null、
  非字符串项和重复项都拒绝，不会静默丢弃。
- 配置非法时，daemon、runtime admin 和写配置路径必须停止，并给出包含字段名的诊断；
  不得用默认值掩盖坏配置，也不得只消费其中看似有效的一部分。

## `/init` 的受控更新边界

`/init <token>` 仍保留 raw YAML document 的受控更新，以免无意义地把所有缺省字段
写回文件，但这不是 schema 旁路：

1. 命令先校验当前完整文档，并从 typed projection 读取已有
   `admin_open_ids` / `bot_open_id`；
2. 它只更新这两个字段，保留其他已校验字段；
3. `save_system_config` 在原子写入前再次校验更新后的完整文档；
4. 任一校验失败时都不写文件，也不更新进程内管理员或 bot identity。

因此，`/init` 不能顺手把未知键、错误列表或启用飞书时的缺失凭证重新保存回去。

## 与其他事实源的关系

`system.yaml` 是实例级静态准入事实：它拥有飞书应用身份、静态管理员/触发身份、网络
策略和群历史回捞参数。群激活与模式、chat binding、thread/runtime lease、live writer
ownership 等动态事实仍由各自 store 和运行时合同拥有。schema 校验不会把这些层合并，
也不会把实时探测到的 bot open id 自动提升为配置事实；只有显式 `/init` 写入成功后，
它才成为下一次启动的静态事实。

## 兼容性结果

过去依赖宽松转换或静默过滤的配置现在会在入口直接失败，包括：拼错或遗留未知键、
加引号的布尔值/数字、标量 open-id、含 null/数字/空值/重复项的列表、非正 timeout、
负数历史参数，以及缺失或空的应用凭证。修复方式是按
`system.yaml.example` 的正式拼写和 YAML 类型修改配置；继续容忍旧解释会保留本合同要
消除的身份与安全歧义。
