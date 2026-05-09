# 跨实例 Live Runtime 准入改造执行清单

关联决策：

- `docs/decisions/cross-instance-live-runtime-admission.zh-CN.md`
- `docs/decisions/shared-backend-resume-safety.zh-CN.md`

目标：

- 把跨实例 live continuation 的安全判断从“只看 lease”升级为
  “先看 global loaded gate，再拿原子 lease”
- 保持现有多实例 thread visibility 与 shared namespace
- 明确产品方向为 `global visibility + cold migration only`

## 1. 要改的行为

### 1.1 attach 准入

- `binding attach`
- `thread attach`
- `service attach`
- detached binding 的自动 attach / re-attach / 下一条消息激活路径

统一改为：

- 先检查目标 thread 是否仍被其他运行中实例报告为 `loaded`
- 若是，则 fail-close
- 若无法验证，也 fail-close
- 只有 gate 通过，才允许继续拿 lease 并 `thread/resume`

### 1.2 本地 `fcodex resume`

检查是否存在“无 lease 但其他实例仍 loaded”的跨实例冲突窗口。

若存在，则：

- `resume <thread_id>`
- `resume <thread_name>`

也要统一走同一套 loaded gate，并在需要时拒绝。

### 1.3 service attach 结果形状

保留当前方向，但要正式收敛成合同：

- 实例级批量恢复
- thread 级 fail-close
- 不同 thread 间允许部分成功
- 结果卡片明确列出 blocked threads 与原因

## 2. 要补的基础能力

### 2.1 global loaded gate helper

新增统一 helper，负责：

- 枚举所有运行中的实例
- 跳过当前实例
- 查询目标 thread 在其他实例中的 loaded 状态
- 对“查询失败 / 无法验证”返回 fail-close 结果

建议输出统一的 reason code / reason text，供：

- `/attach`
- 自动 re-attach
- 本地 `fcodex resume`
- 诊断面

共用。

### 2.2 lease 的角色收敛

保留 `ThreadRuntimeLease`，但明确只负责：

- 原子 claim
- holder 元数据
- 并发竞态防护

不再把它当成“跨实例 live runtime 是否安全”的唯一判断依据。

## 3. 需要补的测试

### 3.1 attach 侧

- 其他实例仍 `loaded` 时，`binding attach` 被拒绝
- 其他实例仍 `loaded` 时，`thread attach` 被拒绝
- `service attach` 对多 thread 做到部分成功，blocked thread 明确列出
- 无法验证其他实例状态时，attach fail-close

### 3.2 自动 re-attach / 激活

- detached binding 的下一条消息激活路径，在跨实例 stale-loaded 冲突时 pure reject
- 不得偷偷 resume 到错误实例

### 3.3 本地 `fcodex`

- 两实例都运行、无 live owner、但另一实例仍报告 `loaded` 时，`fcodex resume`
  必须拒绝
- loaded gate 通过后，仍要验证 lease claim 的原子性

## 4. 需要更新的文档

实现完成后，再同步改正式文档：

- `docs/contracts/runtime-control-surface.{md,zh-CN.md}`
- `docs/contracts/local-command-and-thread-profile-contract.{md,zh-CN.md}`
- `README.md` 中涉及跨实例 attach / resume 的说明

更新方向：

- 不再把 lease 描述成唯一安全事实源
- 明确“loaded gate + lease claim”两层模型
- 明确 `service attach` 的 thread 级 fail-close 合同

## 5. 非目标

本轮不做：

- 跨实例 hot takeover
- 兼容旧的模糊自动接管路径
- 为了便利性放宽 fail-close

如果 loaded 状态不能被明确证明安全，就直接拒绝。
