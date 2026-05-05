# 飞书出站图片结果边界

英文原文：`docs/decisions/feishu-output-images.md`

另见：

- `docs/architecture/feishu-codex-design.zh-CN.md`：当前架构与仓库边界
- `docs/contracts/feishu-thread-lifecycle.zh-CN.md`：执行卡与终态结果载体的生命周期规则
- `docs/decisions/feishu-card-text-projection.zh-CN.md`：当前权威终态文本合同
- `docs/decisions/feishu-attachment-ingress.zh-CN.md`：反方向能力，即飞书附件进入 Codex 的边界

## 1. 问题陈述

用户希望 `feishu-codex` 在飞书侧回复时，能同时给出文本与图片。

这里至少有两类完全不同的出站场景：

1. Codex 在 turn 中显式产出了“图片生成”结果。
2. Codex 通过其他路径让某张图片文件出现在本地，例如 shell 下载、网页抓取、MCP 工具、或手工创建。

本仓库现在已经有清晰的终态文本合同，但还没有对应的“出站图片合同”。

如果不先收紧边界，“支持图片回复”会变得很模糊：

- 图片是否应该塞进运行中的执行卡
- 是否应该作为单独的飞书图片消息发送
- 是否所有本地图片文件都该自动发回飞书
- 服务重启 / reconcile 后是否要重发
- 是否要让其他飞书机器人稳定消费这些出站图片

本文就是为此收紧范围。

## 2. 当前事实

### 2.1 当前仓库行为

当前仓库的基线是：

1. 飞书到 Codex 的图片入口已经存在。
   - 飞书 `image` 附件会被下载并暂存到本地。
   - 它既会作为带路径的文本上下文进入 Codex，也会额外作为 `localImage` turn 输入项进入 Codex。
2. Codex 到飞书的图片出站能力还不存在一等实现。
3. 当前用户可见的 turn 结果路径仍然是纯文本：
   - 运行中的内容进 execution card
   - 权威终态文本进 terminal result card，或回退为普通文本
4. `imageGeneration` 当前只会被当作 execution card 的过程日志材料，而不是可真正发送给飞书用户的图片载体。

因此，当前差距不只是“执行卡片还不能展示图片”。更准确地说，是本仓库目前根本还没有：

- 出站图片载体
- 出站图片去重状态
- 出站图片 reconcile / 重启恢复规则

### 2.2 上游 Codex 事实

上游 Codex 已经提供了一条很有价值的一等图片生成形状：

- turn item 里可能出现 `imageGeneration`
- 该 item 带有：
  - `result`
  - 可选的 `savedPath`
- 上游 core 会尝试把生成出来的图片字节落盘；成功时会写出 `savedPath`
- app-server 的 thread snapshot 也会保留这个 `savedPath`

这里有三个重要推论：

1. `result` 当前确实通常就是图片生成结果的 base64 负载，但本仓库不应把它直接重新定义成自己的通用图片解码合同。
2. `savedPath` 不是对每一个 `imageGeneration` item 都保证存在。
   - 落盘可能失败
   - 负载可能非法
3. 如果要做可靠的出站图片能力，不能只依赖瞬时 notification 流；
   后续还要能从 thread snapshot 中重新读到带 `savedPath` 的 `imageGeneration` item。

### 2.3 飞书平台事实

飞书已经提供了实现可靠“追加式图片投递”所需的基础原语：

- 上传图片资源并获得 `image_key`
- 发送 `msg_type=image` 的图片消息
- 对某条已有消息进行图片引用回复

官方文档：

- 上传图片：
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/image/create`
- 发送消息：
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create`
- 回复消息：
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/reply`

这比把图片强行塞进当前 execution card 的 patch 循环更适合本仓库。

## 3. 为什么现有机制不够

本仓库当前其实已经有两层比较清晰的输出结构：

- execution card
  - 面向人类
  - 可 patch
  - 承担过程日志与阶段性回复 UI
- terminal result carrier
  - 承担权威终态文本合同
  - 负责 `final_reply_text` 的稳定表达

但这两层都不能自然地解决出站图片：

1. execution card 当前是 patch 驱动的文本 UI，不是通用多媒体 transcript 载体。
2. 当前权威终态合同本身就是以文本为中心设计的。
3. 仓库里还没有“某个 turn 的哪些图片已经发给飞书了”的持久化账本。
4. 仓库里也没有对图片结果在 watchdog、reconcile、重启恢复下的正式规则。

所以，图片支持不能被理解成“只要让当前卡片支持图片就行”。那会让文本合同和恢复路径重新变得模糊。

## 4. 第一阶段决策

本仓库的第一阶段出站图片合同应收紧为如下形状。

### 4.1 继续把文本作为唯一权威 round-trip 合同

`final_reply_text` 继续是飞书消息 round-trip、以及下游机器人稳定消费时的唯一权威终态结果合同。

图片只是附加的人类可见产物，不替代 `final_reply_text`，也不进入当前这套强文本投影合同。

### 4.2 只支持显式 `imageGeneration` 输出

第一阶段只支持上游 Codex 显式发出的 `imageGeneration` item。

这意味着：

- 支持：
  - Codex 通过上游图片生成能力产生的图片
- 第一阶段不支持：
  - 工作区里任意出现的图片文件
  - 随手下载到本地的任意图片
  - “从 assistant 文本里猜某个路径应该发图”

原因很简单：

- `imageGeneration` 已经给了仓库一个明确的语义输出项
- 任意本地图片文件没有

### 4.3 用 `savedPath` 作为规范投递输入

第一阶段应把 `savedPath` 视为规范的图片投递输入。

建议规则：

1. 如果某个 `imageGeneration` item 带有非空 `savedPath`，且文件在本地仍存在：
   - 该图片可以进入飞书投递路径
2. 如果 `savedPath` 缺失：
   - 第一阶段不做 best-effort 投递
   - 仍可保留 execution card 里的过程提示，但不要在这里再发明一个自己的 fallback decode 路径

这样职责会更清楚：

- 上游负责图片生成结果的解码与落盘
- 本仓库负责把已经物化到本地的图片工件送到飞书

### 4.4 投递形状：先文本，再 0..N 条图片消息

推荐的飞书侧投递顺序是：

1. 继续发当前已有的权威终态文本载体
2. 然后为同一 turn 追加发送 0..N 条飞书图片回复

这样可以同时获得：

- 稳定的文本语义
- 简单的图片传输
- 不需要重做当前 execution card 的合同

### 4.5 execution card 继续保持文本中心

execution card 可以继续显示 `图片生成` 之类的过程提示，但第一阶段不应把它升级成权威图片载体。

原因：

- 当前 execution card 是 patch 驱动的
- 图片投递天然更适合 append-only
- 如果把终态权威文本与可变图片 UI 混到一张卡里，会明显增加 reconcile、去重和长执行 patch 的复杂度

### 4.6 恢复与去重是硬要求

出站图片能力必须能抵抗恢复路径带来的重复投递。

因此实现时应维护持久化的 turn 级投递状态，例如至少按如下维度记账：

- instance
- chat binding
- thread id
- turn id
- image item id

这份状态必须阻止以下场景的重复发图：

- late reconcile
- watchdog recovery
- service restart
- 同一 turn 被重复做 terminal processing

可以允许一个 fast path：

- 当 `item/completed(imageGeneration)` notification 到来，且其中已经带有可用 `savedPath` 时，立即尝试发图

但 notification 流不能成为唯一依据。恢复路径仍应能通过重新读取 terminal thread snapshot，把还没送达的图片工件补发一次，且只补发一次。

## 5. 明确非目标

第一阶段出站图片能力不解决以下问题：

1. “把任意本地图片文件自动发回飞书”
2. “在运行中的 execution card 里持续 patch 出一整套图片画廊”
3. “把飞书出站图片也纳入当前强文本投影合同”
4. “保证另一个飞书机器人也能稳定把这些图片消息当作机器可读输入消费”

最后这一点尤其重要，因为本仓库当前的飞书触发与文本入口模型，本来就是以文本为中心设计的，并没有定义第二套针对 bot-authored 图片回复的强合同。

## 6. 对两类常见用户期待的影响

### 6.1 “Codex 自己生成了一张图”

这类能力适合在第一阶段支持，但前提是：

- 上游确实发出了显式 `imageGeneration` item
- 且该 item 有可用的 `savedPath`

### 6.2 “Codex 下载或创建了一张本地图片文件”

这类场景在第一阶段不应因为“工作区里现在有张图片”就自动支持。

如果后续真要支持它，就需要新的显式出站合同，例如：

- 上游提供专门的输出 item 类型
- 仓库提供显式 send-image 动作
- 或其他能明确声明“这个本地文件就是要发到飞书”的结构化信号

否则，自动扫描并发送任意本地图片，会非常模糊，也不安全。

## 7. 建议的下一步

如果本仓库要实现出站图片，第一版应故意做窄：

1. 保持现有文本终态合同不变
2. 增加飞书图片上传与图片回复 helper
3. 从 thread snapshot 中收集终态 `imageGeneration` items
4. 只投递带 `savedPath` 的图片生成结果
5. 为 reconcile 与重启恢复持久化每 turn 的图片投递状态

这是在不打乱当前文本合同与 execution card 生命周期的前提下，最清晰、最可维护、也最有实际价值的一条路径。
