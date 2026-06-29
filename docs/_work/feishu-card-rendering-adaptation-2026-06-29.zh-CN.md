# 飞书卡片渲染适配调查与建议

日期：2026-06-29

状态：工作记录。本文只记录调查结论与实现建议，不是已经生效的产品合同。若后续落地，应把明确合同并入 `docs/decisions/feishu-card-text-projection.zh-CN.md`。

## 1. 背景

当前 dev 版本已经把终态权威文本与飞书卡片展示投影分开：

- 权威文本来自 app-server 的原始 `final_reply_text`，写入本实例 `terminal_results.json`
- `terminal_result_id` / checksum 按原始终态文本计算
- 飞书卡片正文可以是 Feishu-safe display projection
- 接收侧 store hit 时必须恢复 store 原文；store miss 时卡片正文只能作为 degraded projection

剩余问题是：飞书卡片富文本不一定按 Codex / LLM 输出的 Markdown 方式渲染。若不要求上游主动适配飞书，则本项目只能在发送卡片前做有限展示层适配。

## 2. 官方渲染边界

参考：

- 飞书富文本 Markdown 组件：<https://open.feishu.cn/document/feishu-cards/card-json-v2-components/content-components/rich-text>
- 飞书表格组件：<https://open.feishu.cn/document/feishu-cards/card-json-v2-components/content-components/table>
- 飞书卡片常见问题：<https://open.feishu.cn/document/common-capabilities/message-card/message-card>

调查结论：

- JSON 2.0 富文本组件支持标题、表情、表格、图片、代码块、分割线等元素。
- 官方说明 JSON 2.0 支持除 `HTMLBlock` 外的标准 Markdown，并支持部分 HTML 标签。
- 代码块要求 fence 和代码内容尽量在行首；四个及以上空格也会触发缩进代码块。
- 有序 / 无序列表要求序号或符号在行首；缩进层级以 4 个空格为准。
- Markdown 图片需要飞书 `image_key`；本地路径或普通外链图片不等价于可渲染图片。
- 链接基本要求 `http` / `https` schema；特殊字符、空格、中文紧贴 URL 等情况可能导致发送失败或渲染异常。
- `<xxx>`、`&copy`、`&reg` 等可能被当成 HTML / 实体处理，导致原文不可见或被改写。
- 富文本 Markdown 表格在 JSON 2.0 中可用，但单个富文本组件最多放置 4 个表格；除标题行外，超过 5 行会分页展示。
- 独立 table 组件单张卡片最多 5 个，最多 50 列；单元格内容过长会省略。
- 卡片整体数据不可超过 30KB，组件嵌套层级不可超过 5 层。

## 3. 当前实现事实

当前本项目已有两类展示层适配：

1. 普通 runtime / help / status 等卡片通过 `sanitize_runtime_markdown_for_feishu_card()` 处理。
   - 位于 `bot/feishu_card_markdown.py`
   - 当前主要处理标题、Markdown 图片、普通 Markdown 链接
2. 终态结果卡通过 `sanitize_terminal_result_markdown_for_feishu_json2()` 处理。
   - 终态权威原文仍写入 store
   - 卡片展示层会替换 Markdown 图片
   - 会规范化 fenced code block，避免列表缩进、嵌套 fence、marker 拼接等导致渲染错位

这个方向是正确的：适配只作用于飞书展示投影，不改变权威文本。

## 4. 建议原则

建议继续采用“有限、可测试的 Feishu-safe display projection”，不要实现完整 Markdown parser。

原则：

- 不改变 `final_reply_text` 权威原文。
- 不在本项目里尝试复刻完整 CommonMark。
- 不把飞书展示投影反向提升为权威文本。
- 只处理明确高风险、可局部修正、可测试的语法。
- 适配器应尽量避免修改 fenced code block 内部内容。
- 高风险内容宁可降级普通文本，也不要发送可能误导接收侧的部分终态卡。

## 5. 优先适配项

建议按以下顺序推进。

1. HTML / XML-like tag 可见化
   - 问题：代码块外的 `<foo>`、`</bar>`、`<T>` 可能被飞书当作 HTML 标签处理。
   - 建议：对非飞书白名单 HTML 标签做转义或插入 `&zwj;`，保证原文可见。
   - 风险：不能在代码块内部替换；否则会破坏代码样例。

2. 链接保守化
   - 问题：非法 schema、含空格、特殊字符未转义、中文紧贴 URL 可能导致发送失败。
   - 建议：只保留明显合法的 `http` / `https` Markdown 链接；其余转成 `label (target)` 或行内 code。
   - 风险：会降低链接可点击性，但提升发送稳定性。

3. 表格数量 / 复杂度降级
   - 问题：富文本单组件最多 4 个 Markdown 表格；独立 table 组件单卡最多 5 个。
   - 建议：先不自动生成 table 组件；检测到过多 Markdown 表格时，把后续表格包进 fenced text。
   - 风险：显示不如原生表格，但更稳定，也避免实现复杂表格 parser。

4. Markdown fence 规则继续收紧
   - 当前已经处理嵌套 fence、缩进 fence、marker 拼接等问题。
   - 后续可继续添加真实失败样例作为 fixture，而不是大范围重写。

5. 列表续行 soft break 硬化
   - 真实案例：
     ```markdown
     1. **明确一次性任务**
        用精确时间：
     ```
   - 问题：飞书富文本组件把一个 Enter 键视为 soft break，渲染时可能忽略；缩进续行又属于同一列表项段落，因此会显示在同一行。
   - 建议：在 fenced code block 外，把“列表项首行 + 缩进续行”的换行显式改成 `<br>`，例如 `1. **明确一次性任务**<br>`。
   - 风险：不能误改 nested list 或 fenced code block。

6. 特殊 HTML entity 风险
   - 问题：`&copy`、`&reg` 等会被当作 HTML 实体。
   - 建议：对明显未闭合或非预期实体做可见化处理。
   - 风险：实体规则复杂，建议只处理真实案例。

## 6. 暂不建议做的事

- 不建议把任意 Markdown 表格自动转换成飞书 table 组件。
  - 原因：列宽、分页、单元格 Markdown、组件数量、数据类型推断都会引入复杂度。
- 不建议使用完整 Markdown parser 作为第一步。
  - 原因：本项目要解决的是飞书显示稳定性，不是通用 Markdown AST 转换。
- 不建议要求上游 Codex 输出飞书专用 Markdown。
  - 原因：这会把平台适配泄漏给模型，且不稳定。
- 不建议让 degraded projection 承担权威语义。
  - 原因：store miss 时卡片正文已经是展示投影，可能和原始终态文本不同。

## 7. 测试建议

建议补一组“飞书渲染风险 fixture”测试，目标是锁定本项目投影合同，而不是模拟飞书完整渲染器。

优先覆盖：

- 列表内 fenced code block
- nested fences
- 列表项缩进续行 soft break
- 代码块外 `<foo>` / `</bar>` / `<T>`
- Markdown 链接里的非法 schema、空格、中文紧贴 URL
- 本地路径图片 `![x](/tmp/a.png)`
- 多个 Markdown 表格
- `&copy` / `&reg` / 未预期 HTML entity

测试断言应集中在：

- 权威 store 文本不变
- 卡片展示 projection 可发送、可见
- marker 不被代码块吞掉
- 高风险内容要么可见化，要么触发普通文本 fallback

## 8. 推荐落地顺序

1. 把 `bot/feishu_card_markdown.py` 明确作为 Feishu-safe display projection 的唯一入口。
2. 先补 HTML / XML-like tag 可见化和链接保守化。
3. 再补 Markdown 表格数量检测与降级。
4. 每次只根据真实失败样例增加小规则和测试。
5. 若某类内容需要大范围结构化转换，再单独讨论是否引入 Markdown AST parser。
