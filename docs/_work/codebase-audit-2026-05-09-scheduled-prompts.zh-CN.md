# scheduled prompt 审视记录 - 2026-05-09

范围：

- 最新提交：`5487579 Add scheduled prompt control-plane support`
- 重点路径：
  - `binding/submit-prompt`
  - `feishu-codexctl prompt send`
  - `feishu-scheduled-prompts` managed skill

## 1. 结论摘要

本轮没有看到新的大面积架构回退，但新增的 scheduled prompt / control-plane 路径里有两处应优先处理的真实行为问题：

1. `binding/submit-prompt` 对不存在的 binding 不会 fail-close，而是会隐式创建新 binding + 新 thread
2. `display_mode=announce` 会先发“开始执行”的说明，再真正尝试启动；若后续启动失败，聊天里会留下误导性成功信号

这两处都不是“文案瑕疵”，而是会直接影响用户对 thread / binding / 定时任务状态的判断。

## 2. Findings

### P0: `binding/submit-prompt` 会对不存在的 binding 隐式建新 thread

涉及代码：

- `bot/runtime_admin_controller.py:384`
- `bot/runtime_admin_controller.py:427`
- `bot/binding_runtime_manager.py:297`
- `bot/prompt_turn_entry_controller.py:204`
- `bot/feishu_codexctl.py:826`

当前行为链路：

1. control plane 接收 `binding/submit-prompt`
2. `submit_binding_prompt_for_control()` 只做“当前 snapshot 是否可写”的检查
3. 当 binding 根本不存在时，`_binding_prompt_check_from_snapshot()` 直接 `allow`
4. 后续 `start_prompt_turn_result()` 进入普通 prompt 入口
5. `ensure_thread()` 发现当前 runtime 没 thread，于是直接 `create_thread()`
6. 最终落下一条新的本地 binding 和记忆之外的新 thread

为什么这是问题：

- 这里的产品面名字和文档都在强调它是 **binding-scoped** 动作
- 调用方传的是 `binding_id`，不是“新建 binding 草稿”
- 因而拼错 `binding_id`、误选实例、定时任务引用旧 binding 时，预期应是 fail-close
- 现在却会静默分叉到一个新的 thread，后续很难排查

本地复现结果：

- 对不存在的 `p2p:ou_typo:chat-typo` 调用 `binding/submit-prompt`
- 返回 `started=true`
- 实际创建了：
  - 新 binding：`('ou_typo', 'chat-typo')`
  - 新 thread：`thread-created`

建议收敛方向：

- 把 `binding/submit-prompt` 明确定义为“只能命中现有 binding”
- binding 不存在时直接拒绝，返回明确 `reason_code`
- 如果后续确实想支持“按原始 chat 标识新建 binding”，也应做成另一条显式入口，而不是复用现有 binding 控制面

### P1: `display_mode=announce` 会先报喜，后续失败时不回补失败说明

涉及代码：

- `bot/codex_handler.py:2110`
- `bot/codex_handler.py:2124`
- `bot/prompt_turn_entry_controller.py:483`
- `bot/prompt_turn_entry_controller.py:523`
- `bot/prompt_turn_entry_controller.py:643`

当前行为：

1. `display_mode=announce` 时，`_submit_prompt_for_control()` 先向 chat 发一条“`<source>触发，开始新一轮执行。`”
2. 然后才进入 `start_prompt_turn_result()`
3. 如果后续在执行卡发送、turn start、自动恢复重试等阶段失败，control plane 只返回 `started=false`
4. 因为这是 control-plane 调用，`surface_failures=False`，不会再向 chat 回一条失败消息

为什么这是问题：

- 对定时任务场景，`announce` 的语义会被用户理解为“这次任务已真正开始”
- 但当前它只表示“准备开始”
- 一旦后续失败，chat 侧信号和真实结果相反，排障体验很差

本地复现结果：

- 构造“执行卡发送失败”场景
- control-plane 返回：
  - `started=false`
  - `reason_code=execution_card_send_failed`
- 但 chat 里已经收到：
  - `schedule触发，开始新一轮执行。`

建议收敛方向：

- 最简单的做法：`announce` 只在真正拿到 `started=true` 后再发
- 或者把文案收紧为“`<source>触发，正在尝试启动。`”，并在失败时补一条失败说明
- 但不建议继续保留“先发成功语气，再静默失败”的组合

## 3. 已验证但未发现新问题的部分

以下路径本轮没有再看到新的 correctness 回退：

- `start_prompt_turn_result()` 基本复用了既有 guard：
  - running-turn
  - detached attach preflight
  - interaction lease
  - all-mode exclusivity
- `binding/submit-prompt` 的 fail-close 返回形状基本清楚：
  - `started`
  - `reason`
  - `reason_code`
- managed skill 的仓库模板与打包副本当前一致，没有发现双份内容漂移

## 4. 本地验证

解释器：

- `/home/zlong/anaconda3/bin/python`

已执行测试：

```bash
/home/zlong/anaconda3/bin/python -m pytest -q \
  tests/test_feishu_codexctl.py \
  tests/test_manage_cli.py \
  tests/test_scheduled_prompt_skill.py \
  tests/test_runtime_admin_controller.py \
  tests/test_codex_handler.py
```

结果：

- `333 passed`

另执行：

```bash
/home/zlong/anaconda3/bin/python -m pytest -q tests/test_prompt_turn_entry_controller.py
```

结果：

- `8 passed`

另做了两组最小人工复现：

1. 不存在 binding 的 synthetic prompt 注入
2. `announce` + 后置启动失败

两组都能稳定复现上文问题。

## 5. 建议优先级

建议处理顺序：

1. 先修“不存在 binding 仍可隐式新建 thread”
2. 再修 `announce` 的时序与失败反馈
3. 然后补对应回归测试，把这两条行为正式锁死

## 6. 明确建议的测试补强

至少补三条：

1. `binding/submit-prompt` 命中不存在 binding 时，必须 fail-close，而不是 create thread
2. `display_mode=announce` 在启动失败时，不得留下误导性的成功语气消息
3. `feishu-codexctl prompt send` 命中错误 binding / 错误实例时，应给出稳定、可操作的拒绝原因
