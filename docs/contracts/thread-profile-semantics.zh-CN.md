# Thread Profile 语义

英文原文：`docs/contracts/thread-profile-semantics.md`

本文只定义 thread-wise next-load state 中 **profile slice** 的业务语义与入口合同。
共享的 next-load 生效与 direct-write / reset-backend 规则，以
`docs/contracts/thread-next-load-settings-semantics.zh-CN.md` 为准。

## 1. 基本事实

- profile 是 **thread-wise** 状态，不是 binding-wise 状态。
- 对受支持的恢复路径，同一个 thread 从 unloaded 恢复为 loaded 时，应使用同一份已持久化的 profile slice。
- 对 unloaded thread，持久化 profile slice 才是事实源。
- 对 loaded thread，事实源改由 live runtime 持有。
- 只有 `profile`、`model`、`model_provider` 三项都齐全时，这份持久化
  profile slice 才算有效；对本项目的受支持路径，遇到不完整记录必须
  fail-close。
- 当前项目不再保留“实例级默认 profile”这一层用户概念。
- 对本项目的显式 profile 改写路径，`profile -> model / model_provider`
  的解析来源是共享的用户级 `CODEX_HOME/config.toml`
  （必要时再用 runtime profile mapping 补 provider）。
- per-cwd / project-local config 被明确排除在这条 thread-wise profile
  slice 合同之外。

## 2. 飞书侧 `/profile [name]` 与 `/profile-clear`

`/profile` 是当前 thread 的正式 profile 管理入口。

它沿用共享的 next-load 设置规则，因此有三类结果：

1. 直接写入
   - 共享 direct-write 条件已满足
2. 提供 “应用并重置 backend”
   - 共享 direct-write 条件未满足，但当前实例可通过 reset-backend 收口
3. fail-closed
   - live runtime 由别的实例持有，或当前实例无法安全重置，或目标
     profile 不能解析成具体的 `profile + model + model_provider` 三元组

其中：

- `/profile <name>`：把当前 thread 的 thread-wise profile 改写为目标三元组
- `/profile-clear`：清空当前 thread 已持久化的 thread-wise profile slice，
  回到“该 thread 未设置 profile override”的状态

## 3. reset-backend 后的状态

通过 `/profile` 触发 backend reset 后：

- binding bookmark 保留
- 相关 Feishu binding 会变成 `detached`
- thread-wise profile/provider 写入成功后立即持久化
- 不自动保证继续接收飞书推送

结果卡必须给用户明确选项：

- `附着当前线程`
- `附着当前实例`
- `保持 detached`

## 4. `/attach` 与 `/detach` 的关系

- `/detach`
  - 只是暂停某个飞书会话接收推送
  - 不等于 thread 已 globally unloaded
- `/attach`
  - 只是恢复推送
  - 不修改 thread-wise profile

也就是说：

- profile 管理与 attach/detach 是两条不同状态轴

## 5. 本地 `fcodex -p`

`fcodex resume <thread> -p <profile>` 只有在 thread 当前未 loaded 时才允许改写 profile。

但允许一条例外的幂等路径：

- 如果请求的有效 next-load profile 设置已等于该 thread 当前持久化设置，
  则即使 thread 仍 loaded，也可按 no-op reuse 继续
- 对 profile 而言，这里的相等判断覆盖完整三元组：
  `profile`、`model`、`model_provider`
- 如果 profile 名字相同，但解析出的 `model` 或 `model_provider`
  已不同，这就不属于 no-op reuse；它仍然是 profile 设置变更，必须走正常的
  direct-write / reset-backend 准入规则
- 这里的“解析出”指的是上面这条 thread-stable 项目合同，不是 upstream
  按 cwd / repo 动态计算出来的结果
- 对于 unloaded thread，普通 `fcodex resume <thread>` 仍应继续使用该 thread
  当前已持久化的三元组，即使这个 profile 名字在本地配置里现在已能解析出不同结果
- 对于 unloaded thread，显式 `fcodex resume <thread> -p <profile>`
  则表示请求该 profile 名字当前的有效设置，并在 resume 前改写持久化三元组
- 对于 loaded thread，普通 `fcodex resume <thread>` 的含义只是接入当前 live runtime；
  它不会主动拿当前本地配置去对账持久化 profile 漂移

如果 thread 仍 loaded，应明确拒绝，并告诉用户：

- 去掉 `-p/--profile` 可直接进入当前会话
- 如果真要改 profile，应等待 thread verifiably globally unloaded
- 常见替代路径是飞书 `/profile <name>` + reset-backend

## 6. 不再支持的旧心智

以下说法当前都不准确：

- “先 release-runtime，再改 profile”
- “只要 unsubscribe，profile 就一定可写”
- “实例有自己的默认 profile，会影响现有 thread”

当前准确说法是：

- profile 是 thread-wise
- next-load 生效与 direct-write 规则，以共享合同为准
- 裸 `codex` 或其他合同外入口直接改动 runtime / config 所造成的分叉，不由本项目兜底统一
