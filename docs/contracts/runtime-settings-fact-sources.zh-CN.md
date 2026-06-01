# 运行时设置的事实源与生效边界

英文原文：`docs/contracts/runtime-settings-fact-sources.md`

本文给出当前项目统一的分析框架，用来区分：

- 写入时到底解析了什么
- 写完以后哪一层是持久化事实源
- 哪个上游边界真正消费它
- 读侧当前看到的是 intent、snapshot 还是 live truth

## 1. 当前三类设置

当前项目把运行时相关设置分成三类：

1. **实例 startup baseline**
   - 当前唯一正式成员：managed backend 的 startup profile
2. **thread-wise next-load state**
   - 当前唯一正式成员：thread memory mode
3. **frontend-owned next-turn settings**
   - model
   - effort
   - approval
   - permissions
   - collaboration mode

这三类设置不能混读、混写、混解释。

## 2. 统一问题清单

判断任一设置时，至少分别回答：

1. 写时解析源
2. 写后持久源
3. 应用边界
4. 读侧视图
5. 当前是否已生效

必要时还要再标记：

- 是否仍处于 provisional / pending 阶段

## 3. 三类设置对照表

| 设置类 | 写后持久源 | 正式应用边界 | 主要读侧 |
| --- | --- | --- | --- |
| 实例 startup profile | 实例配置 `managed_startup_profile` | managed backend 启动 / reset 后重启 | `/profile`、`/status`、本地实例状态 |
| thread-wise memory | `ThreadMemoryModeStore`；必要时 pending seed | `thread/start`、`thread/resume` | `/memory`、thread 状态、resume 诊断 |
| binding-wise next-turn | 当前 binding 的持久化 runtime settings | `turn/start` | `/status`、本轮设置卡片、执行前检查 |

## 4. startup profile

### 4.1 写时解析源

- 目标值按共享 `CODEX_HOME` 中可用 profile-v2 名称解析

### 4.2 写后持久源

- 实例配置字段 `managed_startup_profile`

### 4.3 应用边界

- managed backend 启动
- managed backend reset 后重启

### 4.4 读侧视图

- `/profile` 与 `/status` 读到的是实例级 intent
- 这不是当前 live thread 的 thread-wise truth

## 5. thread-wise memory

### 5.1 写时解析源

- 输入值先归一化成合法 memory mode 枚举

### 5.2 写后持久源

- 正常情况：`ThreadMemoryModeStore`
- provisional 场景：pending threadwise seed

### 5.3 应用边界

- 现有 thread：`thread/resume`
- 新 thread：`thread/start` 的 startup seed 路径

### 5.4 读侧视图

- `/memory` 主要读持久化 intent
- 状态页可附带本次 load 时观测值，但不能假装它是随时可读的 live truth

## 6. binding-wise next-turn 设置

### 6.1 写时解析源

- 来自当前飞书 binding 的命令 / 卡片操作
- `auto` 只表示“不显式覆盖”，不是 thread-wise 持久化写入

### 6.2 写后持久源

- 当前 binding 的持久化 runtime settings

### 6.3 应用边界

- 主路径：`turn/start`

当前实现还有一条窄例外：

- 对 approval / permissions，某些“先 cold-resume 再继续 goal”的路径会在
  resume 阶段额外带一份 one-shot 修正，避免第一轮恢复时回落到错误默认值

这条修正：

- 不改变其事实源仍是 binding-wise next-turn settings
- 也不把 approval / permissions 变成 thread-wise state

### 6.4 读侧视图

- `/status` 与相关设置卡片读的是当前 binding 的持久化 intent
- live runtime 若已被上游其他前端改过，本项目不承诺总能无损读回

## 7. pending / provisional

下列场景必须承认仍是 provisional：

- thread 刚创建，还没稳定 materialize
- `thread/start` 返回结果未知
- backend reset 后正在替换 provisional thread

这时可以有临时 seed，但不能把它伪装成正式 thread/store 真相。

## 8. 一条判断原则

如果某个问题是在问：

- “下次 backend 启动会带什么”

先看 startup profile。

如果它是在问：

- “下次恢复这个 thread 会带什么”

先看 thread-wise memory。

如果它是在问：

- “当前飞书会话下一轮会带什么”

先看 binding-wise next-turn settings。
