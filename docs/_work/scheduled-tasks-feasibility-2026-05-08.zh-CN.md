# 定时任务与延迟续跑能力可行性分析 — 2026-05-08

Status: working material under `docs/_work/`. Not a repository fact.

2026-05-09 更新：

- 当前目标已明确收敛为**短期方案**
- 推荐路线调整为：
  1. `binding/submit-prompt`
  2. `systemd --user` timer/service
  3. 一个教模型管理这些 timer 的 skill
- 内建 `feishu-codex` scheduler 保留为后续可选演进方向，不作为当前建议

## 1. 问题定义

当前需求分两类：

1. 用户在这一轮里交代一个需要较长观察窗口的任务，允许当前轮先结束，再由系统在未来某个时间点自动继续同一条对话线程。
2. 系统每天定时执行一类固定分析任务，例如股市复盘，并把结果回到飞书会话里。

这两类需求的共同核心都不是“做一个独立的外部机器人”，而是：

- 在未来某个时间点，**安全地继续当前 `feishu-codex` 已绑定的同一个 Codex thread**
- 尽量复用当前实例的 shared backend
- 不额外制造一个新的裸 `codex` / 新的 isolated app-server 进程

## 2. 当前代码里的硬事实

### 2.1 已经存在稳定的 prompt 启动链路

飞书入站消息最终会进入：

- `bot/feishu_bot.py`
- `bot/inbound_surface_controller.py`
- `bot/codex_handler.py::_handle_prompt(...)`
- `bot/prompt_turn_entry_controller.py::handle_prompt(...)`

而 `PromptTurnEntryController.start_prompt_turn(...)` 会：

- 解析当前 binding
- 确保已有 thread 或创建 thread
- 确保当前 binding 已接到该 thread 的 runtime
- 调 `start_turn(...)` 在该 thread 上开启新一轮执行

因此，从“未来触发一次新 prompt”的角度看，现有执行面已经完整，缺的只是一个**非飞书入站消息**的触发入口。

### 2.2 已经存在本地 control plane

`bot/service_control_plane.py` 已提供：

- 仅监听 `127.0.0.1`
- 基于 owner token 的鉴权
- method + params 的 JSON 请求分发

`bot/codex_handler.py` 已把 control request 串行路由到：

- `RuntimeAdminController.handle_service_control_request(...)`

这意味着：

- 本地已经有一条正式的“服务内管理入口”
- 不需要为了 scheduler 再额外开一个 HTTP server 或第二个守护进程

### 2.3 当前 control plane 还没有“提交 prompt”能力

当前 `RuntimeAdminController` 暴露的 thread 级控制面包括：

- `thread/status`
- `thread/bindings`
- `thread/attach`
- `thread/detach`
- `thread/archive`
- `thread/send-image`

其中 `thread/send-image` 是一个很重要的信号：

- control plane 已经不只是“只读状态查看”
- 它已经支持 thread-scoped 的主动出站能力

但目前还没有：

- `thread/send-text`
- `thread/submit-prompt`
- `binding/submit-prompt`

也就是说，**现有架构差的是一个很薄的 prompt injection 能力，不差整个调度框架**。

### 2.4 当前仓库已有 shared-backend 安全边界

`docs/decisions/shared-backend-resume-safety.zh-CN.md` 已明确收紧：

- 同一 thread 应只通过一个 backend 写入
- 若两个前端通过不同 app-server 进程恢复同一 persisted thread，可能各自物化 live 副本并冲突
- Feishu 与本地继续同一 live thread 的安全路径，应统一走同一个实例 backend

因此，凡是会额外启动一个新 app-server 的方案，都不应作为默认推荐路径。

## 3. 公开信息与本机环境补充

### 3.1 本机确实已有 `lark-cli`

本机已安装飞书官方 CLI 包 `@larksuite/cli`，本地 README 明确写出：

- 该工具支持 `im +messages-send`
- 支持 `--as bot` / `--as user`
- 支持直接调用任意开放平台 API

公开来源：

- <https://github.com/larksuite/cli>

本机安装位置示例：

- `/home/zlong/.local/share/fnm/node-versions/v25.9.0/installation/bin/lark-cli`

### 3.2 但当前不应把 `lark-cli` 当主触发面

截至 `2026-05-08` 本机实测：

- `lark-cli` 需要显式补 `node` 到 `PATH` 才能执行
- `lark-cli auth status` 显示：
  - user token 已在 `2026-04-26` 过期
  - refresh token 已在 `2026-05-03` 过期
  - 当前只剩 bot identity 可用

这说明：

- 把定时能力压在 `lark-cli --as user` 上，运维依赖偏重
- 它适合作为备用外部触发器，不适合作为默认基础设施

### 3.3 飞书 bot 主动发消息在当前仓库里已被本地代码验证

当前 `bot/feishu_bot.py` 已直接使用：

- `client.im.v1.message.create(...)`
- `client.im.v1.message.reply(...)`

并封装成：

- `send_message(...)`
- `send_message_get_id(...)`
- `reply(...)`
- `reply_to_message(...)`

所以“服务主动把结果回给飞书”这件事，在当前实现中已经是现成能力，不构成 scheduler 的主要阻碍。

## 4. 方案比较

### 4.1 方案 A：外部定时器 -> `lark-cli` 给当前飞书会话发一条消息

形态：

- `cron` / `systemd --user` timer 到点执行
- 调 `lark-cli im +messages-send ...`
- 让飞书把这条消息再次作为入站事件交给 `feishu-codex`

优点：

- 对 `feishu-codex` 代码改动最少
- 复用现有飞书入站 prompt 链路

缺点：

- 依赖独立的 `lark-cli` 认证状态
- 依赖本机 `node` / PATH / CLI 环境
- 触发面绕远了：先出站发消息，再等飞书回投为入站
- 对“bot 自己给自己发消息是否稳定再触发 inbound”不应做过强假设

判断：

- 可以作为备用方案
- 不应作为默认推荐方案

### 4.2 方案 B：外部定时器 -> 本地 control plane 新增 `submit-prompt`

形态：

- `cron` / `systemd --user` timer 到点执行一个本地 helper
- helper 直接调 control plane
- control plane 在目标 binding / thread 上合成一次 prompt turn

推荐的接口形状：

- `binding/submit-prompt`
  - 入参：`binding_id`, `text`, 可选 `actor_open_id`, `input_items`, `synthetic_source`
- 或 `thread/submit-prompt`
  - 入参：`thread_id`, `text`
  - 但仍要在内部解析唯一 attached binding，或定义 fan-out 语义

优点：

- 直接复用当前实例 backend
- 不引入第二套飞书鉴权依赖
- 不需要模拟“再发一条飞书消息”
- 与当前 `thread/send-image` 的设计方向一致

缺点：

- 需要改 `feishu-codex`
- 需要明确 synthetic prompt 的用户面语义

判断：

- 这是**当前最推荐的近期方案**

### 4.3 方案 C：在 `feishu-codex` 内建 scheduler

形态：

- 在实例 data dir 下持久化 job
- 服务启动时加载 job
- 计算下一次触发时间，到点后内部直接走方案 B 的 `submit-prompt`

优点：

- 用户体验最好
- 不依赖外部 crontab 状态
- 可以做 `schedule add/list/remove/run-now`

缺点：

- 比方案 B 多一层 job persistence / timer lifecycle
- 需要额外考虑服务重启补偿与漏跑策略

判断：

- 这是**中期最推荐的正式产品化方案**
- 但不应跳过方案 B，最好先把 prompt injection surface 收敛清楚

### 4.4 方案 D：单独脚本直接用 Codex SDK `thread_resume(...)`

形态：

- 独立 Python 脚本调用 `codex_app_server`
- 直接 `thread_resume(thread_id)` 然后 `run(...)`

优点：

- 从写脚本的角度很直观

缺点：

- 默认会自行启动一个新的 `codex app-server` `stdio://` 子进程
- 与当前实例 shared backend 脱钩
- 可能触发“同一 persisted thread 被不同 backend 恢复”的 live 副本冲突风险

判断：

- 技术上可做
- **不应作为本仓库的默认调度方案**

## 5. 推荐路线

当前推荐分三步，但都是围绕**短期可落地方案**展开：

### 5.1 第一步：先补 prompt injection control surface

先做一个最小、明确、线程安全的入口：

- 首选：`binding/submit-prompt`

推荐原因：

- `binding` 才是飞书会话的真实用户面
- 可以直接复用当前 binding 上的 cwd / approval / sandbox / profile / attached runtime 语义
- 避免 `thread` 绑定多个 chat 时的目标不明确问题

最小能力建议：

- 指定 `binding_id`
- 指定 `text`
- 指定是否显示“这是系统定时触发”
- 允许内部生成 synthetic `message_id=""`

明确不做：

- 不在第一版做跨 binding fan-out prompt
- 不在第一版做复杂队列
- 不在第一版做多轮 DAG workflow

### 5.2 第二步：用 `systemd --user` 提供短期调度壳

第二步不做内建 scheduler，而是直接采用：

- `systemd --user` timer

让它在到点时执行一个本地 helper，由 helper 去调用：

- `binding/submit-prompt`

这样可以把以下基础设施问题外包给成熟的 `systemd`：

- 定时触发
- 开机 / 登录后恢复
- 漏跑补偿（例如 `Persistent=true`）
- 单元级状态查看
- 日志与失败排查
- 启停 / 删除 / 列表化管理

### 5.3 第三步：加一个教模型管理 `systemd` 任务的 skill

第三步不要求 `feishu-codex` 内建 `schedule add/list/remove`，而是新增一个 skill，职责是：

- 理解自然语言中的时间表达
- 生成或更新对应的 `systemd --user` unit
- 把业务 prompt 交给 helper 或 `feishu-codexctl prompt send`
- 回显创建结果、下次触发时间、删除方式

这个 skill 适合承接类似话术：

- “明天 09:35 继续昨天的市场分析”
- “每个交易日 15:25 给我做 A 股收盘复盘”
- “取消昨晚创建的那个定时任务”

## 6. 为什么短期更推荐 `systemd --user` + skill

如果目标是本机个人使用、尽快落地，Linux 上更建议：

- `systemd --user` + skill

原因：

- skill 只需要负责“自然语言 -> unit/helper 参数”的翻译
- `systemd` 已经提供成熟的定时、持久化、状态、日志、补跑能力
- 不需要现在就在 `feishu-codex` 内实现 job store / 去重 / 重跑补偿 / 并发调度器
- 更容易先做出能长期自用的版本

当前不推荐短期内直接做内建 scheduler 的原因：

- 工程量明显更大
- 需要自己定义和验证 job 持久化合同
- 需要自己处理去重、漏跑、并发、重试、日志与迁移
- 对当前“本机个人使用”的场景来说投入产出比不高

`cron` 仍可用，但更适合作为最低配 fallback。

## 7. 对两类目标任务的具体适配

### 7.1 延迟续跑 / 观察后继续

适配方式：

- 当前轮先给出阶段结论
- 同时登记一个未来触发的 prompt，例如：
  - “请继续检查昨晚启动的回测任务结果”
  - “请在明天 09:35 重新评估市场开盘后的板块强弱”

短期方案里，这类 job 不要求先在 `feishu-codex` 内部持久化。

建议最小落点是：

- 一个稳定的 unit 命名规则
- 一个 unit -> `binding_id` / `prompt_text` / `run_at` 的映射
- 一份可被 skill 读取和维护的本地元数据

其中：

- 定时与漏跑补偿交给 `systemd`
- prompt 安全执行交给 `binding/submit-prompt`
- 人类可读的任务描述与管理入口交给 skill

### 7.2 每日定时股市分析

适配方式：

- 直接把分析 prompt 固化成一个 `systemd --user` timer + service
- 到点后由 helper 在同一飞书会话里触发一轮新的 stock-analysis

建议先做两类典型时点：

1. `15:20` 到 `15:40`
   - A 股收盘后当日复盘
2. 次日 `08:30`
   - A 股盘前，顺带并入隔夜美股与当日港股前瞻

## 8. 建议的第一阶段接口草案

这里只给最小草案，不视为正式契约。

### 8.1 control plane

新增 method：

- `binding/submit-prompt`

入参建议：

```json
{
  "binding_id": "p2p:ou_xxx:oc_xxx",
  "text": "请继续昨天的分析，并结合今天最新市场情况更新结论。",
  "synthetic_source": "schedule",
  "display_mode": "silent"
}
```

第一阶段返回值建议：

```json
{
  "binding_id": "p2p:ou_xxx:oc_xxx",
  "thread_id": "thr_xxx",
  "started": true,
  "turn_id": "turn_xxx",
  "reason": ""
}
```

### 8.2 `feishu-codexctl`

新增命令建议：

- `feishu-codexctl prompt send --binding-id <id> --text <text>`

短期方案下，不要求当前就扩展内建 `schedule` 命令面。

更实际的做法是：

- 先让 skill 调用一个 helper
- helper 再使用 `feishu-codexctl prompt send ...`

### 8.3 skill / helper

短期建议把“创建定时任务”的智能入口放在 skill，而不是放在 `feishu-codex` 内建 scheduler。

skill 负责：

- 解析时间
- 生成 unit 名称
- 写入或更新 `systemd --user` timer/service
- 维护一份本地元数据索引

helper 负责：

- 在真正触发时调用 `feishu-codexctl prompt send --binding-id ... --text ...`

如果后续要继续扩展，再考虑：

- `feishu-codexctl schedule add ...`
- `feishu-codexctl schedule list`
- `feishu-codexctl schedule remove <job_id>`
- `feishu-codexctl schedule run-now <job_id>`

## 9. 需要显式保持的安全边界

1. 不要用一个新开的裸 Codex backend 去恢复当前飞书正在使用的 thread。
2. `systemd` 只负责“何时触发”，真正的 prompt 执行仍要经过当前的 running-turn / interaction-lease / attach-check 保护。
3. 若目标 binding 当前不可写，应 fail-closed 返回拒绝原因，而不是静默排队。
4. 第一阶段不做“自动抢占另一实例 owner backend”。
5. 定时任务只是“未来时点发起一次 prompt”，不是后台常驻双写执行器。

## 10. 当前结论

截至 `2026-05-09`，基于本仓库代码、本机环境与当前目标收敛后的综合判断：

- 这项能力**完全可做**
- 最稳妥的落地顺序是：
  1. 先给 `feishu-codex` 增加 `binding/submit-prompt`
  2. 再在外层接 `systemd --user` timer/service
  3. 再加一个教模型管理这些 timer 的 skill

不推荐的默认路径：

- 直接用独立 Codex SDK helper 恢复 thread
- 把 `lark-cli` 消息回环当成唯一正式触发基础设施

当前明确降级为“后续可选项，而非当前推荐项”的路径：

- 在 `feishu-codex` 内立即内建完整 scheduler 子系统

## 11. 相关代码入口

- `bot/prompt_turn_entry_controller.py`
- `bot/codex_handler.py`
- `bot/runtime_admin_controller.py`
- `bot/service_control_plane.py`
- `bot/feishu_codexctl.py`
- `bot/feishu_bot.py`

## 12. 相关文档

- `docs/decisions/shared-backend-resume-safety.zh-CN.md`
- `docs/architecture/fcodex-shared-backend-runtime.zh-CN.md`
- `docs/architecture/feishu-codex-design.zh-CN.md`

## 13. 公开参考

- `@larksuite/cli` README
  - <https://github.com/larksuite/cli>
- OpenAI Codex SDK / app-server public repo
  - <https://github.com/openai/codex>
