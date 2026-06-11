# 飞书原卡查询、JSON 2.0 终态卡与转发读取决策

另见：

- `docs/decisions/feishu-card-text-projection.zh-CN.md`：当前 best-effort 文本投影边界
- `docs/architecture/feishu-codex-design.zh-CN.md`：当前架构与模块边界
- `docs/contracts/feishu-thread-lifecycle.zh-CN.md`：执行卡与终态收口生命周期
- `docs/doc-index.zh-CN.md`：文档索引

## 1. 问题陈述

用户希望同时满足两个目标：

- 终态卡在飞书里正确显示分级标题、列表、引用、代码、链接等结构
- 终态卡被直接发送、直接转发、或合并转发后，`feishu-codex` 仍能尽可能高保真地读取其内容，而不是退化成纯文本猜测

围绕这个目标，之前的讨论里出现过两个过度简化的判断：

- “JSON 1.0 更适合保真读取，JSON 2.0 只能解决显示”
- “只要收到 merge_forward，就等于直接拿到完整原卡 JSON”

这两种说法都不准确。

按飞书当前官方文档：

- 卡片消息默认返回的是“接收消息结构”，不是发送时的原始卡片 JSON
- 但 `message/get` 与 `message/list` 在带 `card_msg_content_type=user_card_content` 时，可以返回发送时的原始卡片 JSON
- 这条能力同时覆盖卡片 JSON 1.0 与 2.0
- `merge_forward` 外层消息内容固定为 `Merged and Forwarded Message`
- 对 `merge_forward`，应先展开子消息，再对子消息逐条做后续查询

因此，真正需要的不是继续围绕“1.0 还是 2.0”二分争论，而是定义：

- 哪些场景应优先走“按 `message_id` 查询原卡 JSON”
- 哪些场景只能继续走 best-effort 投影
- 如何在重启、转发、跨会话、旧实例残缺日志等情况下，判断本项目到底收到了什么

## 2. 决策摘要

本仓库关于终态卡显示与读取的决策如下：

1. 终态卡显示方向切换到 **JSON 2.0 优先**。
2. “高保真读取”不再依赖默认事件体或默认历史列表结构，而应优先依赖：
   - 目标消息的 `message_id`
   - `message/get` 或 `message/list`
   - `card_msg_content_type=user_card_content`
3. 读取架构采用三段式：
   - 可按 `message_id` 精确查询：走原卡读取
   - `merge_forward`：先展开子消息，再尽量走原卡读取
   - 其余情况：best-effort 投影
4. `merge_forward` 不是“完整原卡 JSON 本体”，只是“进入子消息展开链路的入口”。
5. 普通转发不承诺保留原始源消息 ID，但若转发后的新消息本身仍为 `interactive`，则仍可能通过这条新消息的 `message_id` 读取其完整卡片 JSON。
6. `/last text` 保留为兜底能力，不再被视为唯一权威路径。
7. 当前阶段不设计新的 `/text` 功能；优先把“直接读取转发卡片本身”做成主路径。
8. 为支持重启后验证，必须补充一套“原始接收观测”能力，明确记录：
   - 原始事件体里收到的 `msg_type`
   - 外层消息 `message_id`
   - 对 `merge_forward` 展开后拿到的子消息 `message_id`
   - 是否拿到了原卡 JSON
   - 最终是走了原卡读取还是投影回退

## 3. 为什么是 JSON 2.0 + 原卡查询

### 3.1 JSON 1.0 的主要问题在显示层

当前项目的终态卡正文路径里，飞书客户端对 JSON 1.0 / markdown 子集的分级标题支持较弱。

这带来两个直接后果：

- `#` / `##` 等层级在用户端显示不理想
- 为适配显示，发送侧不得不做显式 sanitize，从而引入额外的信息折叠

因此，继续坚持 JSON 1.0 的主要收益并不是“天然更保真”，而只是：

- 当前项目已有的 best-effort 文本投影路径对它更熟悉
- 默认历史结构里它更容易被投影成可用文本

这不是长期设计优势。

### 3.2 JSON 2.0 的主要收益在显示与结构表达

JSON 2.0 的强项是：

- 更适合终态结构化表达
- 更有希望正确显示标题层级、列表、引用、代码、链接
- 更适合把“展示正文”和“可机器读取结构”统一到同一份卡片合同中

因此，终态卡主显示路径应优先升级到 JSON 2.0。

### 3.3 读回保真与否，关键不在 1.0/2.0，而在是否查询原卡

如果只靠：

- 接收事件体
- 默认 `message/list`
- 当前 `project_interactive_card_text(...)`

那么不论 1.0 还是 2.0，本质上都还是在吃飞书的“默认回传结构”，属于投影路径，不属于高保真读取。

只有在带 `card_msg_content_type=user_card_content` 时，读取链路才升级为“原卡 JSON 读取”。

这时：

- 1.0 与 2.0 都可以走高保真
- 2.0 也不再天然弱于 1.0

所以真正的分界不是卡片版本，而是：

- 有没有可用的 `message_id`
- 有没有走原卡查询

## 4. 正式术语

### 4.1 默认投影读取

指不额外要求原卡格式，只消费：

- 接收事件里的默认 `content`
- 或 `message/list` / `message/get` 默认返回的卡片结构

再通过本项目的投影逻辑抽取文本。

这是 best-effort，不承诺完整保真。

### 4.2 原卡读取

指对目标消息使用：

- `message/get`
- 或 `message/list`

并显式传入：

- `card_msg_content_type=user_card_content`

从而取得发送时的原始卡片 JSON。

### 4.3 高保真读取

本决策里的“高保真”定义为：

- 终态正文可恢复
- 标题层级可恢复
- 列表、引用、代码、链接等结构可恢复
- 使用的是卡片结构本身，而不是纯文本猜测

这里不要求逐字符还原发送前原始 Markdown 字符串。

### 4.4 普通转发

指飞书“转发消息”生成的一条新消息。

它有自己的 `message_id`。文档没有承诺保留原始源消息 ID。

### 4.5 合并转发 `merge_forward`

指飞书的合并转发消息类型。

它的外层消息内容固定为：

- `Merged and Forwarded Message`

后续应通过查询接口拿到其中的子消息，再对子消息分别处理。

## 5. 官方合同边界

### 5.1 `message/get` 与 `message/list`

飞书官方文档当前明确写明：

- 不传 `card_msg_content_type` 时：
  - 返回默认卡片结构
  - 不支持返回发送时的原始卡片 JSON
- 传入 `user_card_content` 时：
  - 返回发送时的原始卡片 JSON
  - 同时覆盖卡片 1.0 与 2.0

因此，“JSON 2.0 无法被原样读回”的旧判断应视为失效。

### 5.2 `merge_forward`

飞书官方文档当前明确写明：

- 合并转发生成的新消息内容固定为 `Merged and Forwarded Message`
- 其中的子消息可以通过“获取指定消息的内容”接口获取
- 对 `merge_forward` 调 `message/get` 时，返回的 `items` 中会包含：
  - 1 条合并转发外层消息
  - N 条子消息
- 子消息对象有 `message_id`
- 合并转发场景会返回 `upper_message_id`

但文档没有明确承诺：

- 子消息 `message_id` 一定等于“最初源消息的 message_id”
- 所有类型消息在合并转发后都绝不丢信息

因此，本项目只能正式宣称：

- `merge_forward` 提供“子消息可继续查询”的官方路径
- 不能宣称“merge_forward = 绝不丢信息”

### 5.3 普通转发

飞书“转发消息”文档说明的是：

- 调用该接口会生成一条新的消息
- 新消息有自己的 `message_id`
- 新消息类型可以是 `interactive`

但文档没有承诺：

- 会返回原始源消息 ID
- 会附带某种统一的“源消息引用元数据”

因此，普通转发的正式边界是：

- 可能丢失原始源消息 ID
- 但如果转发后的新消息本身仍是 `interactive`，则仍可能通过“新消息自己的 `message_id`”读取到其完整卡片 JSON

## 6. 读取架构决策

### 6.1 总体原则

读取路径不再按“1.0 / 2.0”分支，而按“文本来源权威性与读取保真度”分支：

1. 本地 terminal result store 命中：权威终态文本
2. 可按 `message_id` 查询当前消息的原卡 JSON：raw-card projection
3. 其他情况：payload / best-effort projection

### 6.2 普通 `interactive` 消息

当收到一条普通 `interactive` 消息时：

1. 优先对当前这条消息自己的 `message_id` 调 `message/get`，并设置
   `card_msg_content_type=user_card_content`
2. 若能拿到原卡 JSON，则按本项目卡片协议做 raw-card projection
3. 对新版终态卡，只有 `terminal_result_id` 能在本机器人实例本地 terminal result store
   中命中且 checksum 匹配时，store 正文才是权威文本
4. 对 store miss 的新版终态卡、没有 `result_id` 的历史终态卡、以及其他交互卡片，
   原卡 JSON 只能提供非权威投影
5. 若原卡读取失败，则回退到事件 payload / 默认结构的 best-effort 投影

这里要特别注意：

- 不需要先知道“原始源消息 ID”
- 当前消息自己的 `message_id` 就足够成为高保真读取入口
- 高保真读取不等于权威文本；权威文本只来自本地 store 命中

### 6.3 `merge_forward`

当收到 `merge_forward` 时：

1. 不把外层固定文案当成内容本体
2. 用外层 `message_id` 调 `message/get`
3. 获取其中的子消息列表
4. 对每条子消息分别处理：
   - 若是 `interactive`，再按其 `message_id` 查询原卡 JSON
   - 若是 `text` / `post` 等，走现有文本路径
5. 对本项目终态卡候选子消息，仍按同一套三档合同处理

所以：

- `merge_forward` 不是原卡 JSON
- `merge_forward` 是进入“子消息展开 + 原卡读取”的入口

### 6.4 其他情况

当既没有：

- 普通 `interactive` 的可用原卡读取
- 也没有 `merge_forward` 的子消息展开结果

就只能回退到：

- 当前 payload / best-effort 投影
- 或 `/last text`

## 7. 终态卡协议方向

### 7.1 单份权威正文

后续 JSON 2.0 terminal result card 的正式方向是：

- 只保留单份权威正文
- 不再为“怕丢语义”额外放一份相同正文的隐藏副本

原因：

- 如果原卡查询能力可用，卡片正文可作为高保真 projection 输入；是否权威仍取决于
  本地 terminal result store 是否命中
- 双份正文只是在默认投影链路受限时的补偿手段

### 7.2 结构化正文块

终态卡应有一个稳定、可定位的正文块位，用于：

- 用户显示
- 机器读取

推荐要求：

- 终态正文必须位于一个固定的 rich text / content block
- 解析器只认这一个块位
- 标题、列表、引用、代码、链接等结构都从该块位恢复

### 7.3 结构摘要的角色

该兼容层已经移除。

当前终态卡协议只保留：

- 标题与模板合同
- `final_reply_text` 正文
- 隐藏 marker
- 新版卡片正文元素上的 `fc_tr_<result_id>_<checksum>` 引用

因此当前行为变成：

- 原卡查询成功且 `result_id` 可从本地 terminal result store 恢复时：以
  store 正文为权威结果
- 原卡查询成功但 store miss 时：卡片正文只作为 degraded projection 回退
- 原卡查询失败时：只剩 best-effort 投影，不再依赖结构摘要修复标题层级

## 8. 当前仓库与目标状态的差距

当前仓库现实是：

- 历史读取主要仍走 `message.list`
- 未设置 `card_msg_content_type=user_card_content`
- `merge_forward` 路径只是把子消息展开后做文本提取
- 接收入口没有一套正式的“原始事件观测日志”

也就是说，当前实现仍处于：

- 默认历史结构
- best-effort 投影
- merge_forward 文本展开

而不是：

- 原卡读取优先
- merge_forward 子消息原卡读取

## 9. 实施计划

### 9.1 阶段一：抽象原卡读取能力

在飞书接入层新增正式能力：

- `get_message_raw(message_id, *, card_msg_content_type="user_card_content")`
- `list_messages_raw(..., card_msg_content_type="user_card_content")`

要求：

- 与现有默认结构接口并存
- 不直接替换当前 best-effort 流程
- 对返回结构做兼容包装，避免 SDK 参数形态变化时直接炸裂

### 9.2 阶段二：建立三段式读取决策

正式引入一个读取决策层：

1. 目标消息是否是普通 `interactive`
2. 是否可直接按当前消息 `message_id` 读原卡
3. 是否是 `merge_forward`
4. 若是，是否可展开子消息
5. 子消息中是否存在可按协议识别的 terminal result card
6. 若都失败，再回退投影

### 9.3 阶段三：终态卡升级到 JSON 2.0

发送侧将 terminal result card 迁移为 JSON 2.0，要求：

- 正文仅保留一份
- 正文区块稳定可解析
- 标题层级、列表、引用、代码、链接优先靠结构表达

### 9.4 阶段四：保留 `/last text` 兜底

`/last text` 继续存在，但定位改为：

- 当直接读取卡片失败时的兜底
- 当用户只想快速取最近结果时的便捷命令

它不再被视为唯一权威路径。

## 10. 观测与调试设计

这部分是本决策的关键补充。

原因是：

- 用户稍后会要求执行本计划中的改造
- 执行完成后会重启服务
- 重启后，用户会把卡片转发给机器人
- 机器人最终看到的，可能已经是本项目处理后的文本，而不是肉眼能直接确认的原始事件形态

因此，必须在实现里增加一种“可以明确知道本项目到底收到了什么”的观测能力。

### 10.1 需要观测的事实

至少要稳定记录以下事实：

- 原始接收事件的 `message_type`
- 原始接收事件的外层 `message_id`
- 原始接收事件的 `chat_id`
- 原始接收事件的 `thread_id`
- 原始接收事件的 `parent_id`
- 原始接收事件的 `root_id`
- 原始接收事件里的原始 `content`
- 若为 `merge_forward`：
  - 对外层 `message_id` 调 `message/get` 后得到的 `items` 数量
  - 每个子消息的 `message_id`
  - 每个子消息的 `msg_type`
  - 每个子消息的 `upper_message_id`
- 若对子消息或普通 `interactive` 做了原卡查询：
  - 是否设置了 `card_msg_content_type=user_card_content`
  - 查询是否成功
  - 返回的是默认结构还是原卡 JSON
  - 卡片 schema 是 `1.0` 还是 `2.0`
- 最终采用的路径：
  - `raw_card_direct`
  - `raw_card_from_merge_forward_child`
  - `best_effort_projection`
  - `last_text_fallback`

### 10.2 建议的实现形态

不建议把完整原始事件 JSON 无差别常驻写入普通 info 日志。

建议增加：

- 一组结构化调试日志
- 受配置开关控制
- 可单独 grep

推荐日志事件名：

- `card_ingress_event`
- `card_ingress_merge_forward_expansion`
- `card_ingress_raw_card_fetch`
- `card_ingress_resolution`

### 10.3 最小验证开关

建议新增布尔配置，例如：

- `debug_raw_card_ingress`

开启后：

- 记录上面列出的结构化事实
- 默认关闭，避免常态日志膨胀

### 10.4 为什么必须加这套观测

因为稍后的真实验证场景是：

- 服务重启后
- 用户从飞书客户端把卡片转发给机器人
- 机器人收到的是生产链路里的真实事件

如果没有这套观测，排障时只能看到：

- 处理后的文本
- 或少量默认日志

那将无法分辨：

- 飞书事件本来就只给了文本
- 还是项目在接收层把卡片压平了
- 还是 merge_forward 已经展开，但后续没查原卡
- 还是查了原卡，但被权限或参数问题拦住了

## 11. 推荐验证顺序

### 11.1 第一轮：普通卡片直收

目标：

- 自己发送一张 JSON 2.0 terminal result card
- 确认对该消息自己的 `message_id` 能原卡读取

成功标准：

- 读到 `schema`
- 读到原卡正文块
- 不依赖当前投影逻辑也能恢复终态内容

### 11.2 第二轮：普通转发

目标：

- 把该卡片直接转发给机器人
- 观察收到的是：
  - `interactive`
  - 还是退化成 `text`

成功标准：

- 若仍是 `interactive`，可直接用这条转发后消息自己的 `message_id` 原卡读取
- 若退化成 `text`，明确记录为普通转发不适合作为主路径

### 11.3 第三轮：合并转发

目标：

- 把该卡片以 `merge_forward` 方式转发给机器人
- 确认外层消息展开后能拿到子消息

成功标准：

- `message/get` 返回 `1 + N` 条 `items`
- 子消息里存在 `interactive`
- 可对子消息继续做原卡读取

### 11.4 第四轮：回退验证

目标：

- 模拟原卡读取失败
- 确认当前 best-effort 投影和 `/last text` 仍可工作

## 12. 当前产品结论

基于当前文档与代码调查，本仓库的正式产品方向应更新为：

- 显示优先使用 JSON 2.0
- 高保真读取优先使用“按 `message_id` 查询原卡 JSON”
- `merge_forward` 作为子消息展开入口，而不是完整内容本体
- 普通转发是否可靠，取决于转发后是否仍保留可查询的 `interactive` 新消息
- `/last text` 是兜底，不是唯一权威路径
- 是否真正可把“转发卡片本身”作为主路径，必须依赖后续加日志后的实测结果

## 13. 对当前实现的直接要求

后续执行本方案时，至少要同时交付两类改动：

1. 功能改动
   - 原卡查询接口
   - merge_forward 子消息原卡读取
   - JSON 2.0 terminal result card

2. 观测改动
   - 结构化 ingress 调试日志
   - 可确认“本项目实际收到了什么”的最小证据链

如果只做功能改动，不补观测，将无法在用户后续“重启后转发卡片”的真实实验里有效定位问题。
