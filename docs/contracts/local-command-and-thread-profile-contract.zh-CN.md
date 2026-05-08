# 本地命令与 Thread Profile 合同

英文原文：`docs/contracts/local-command-and-thread-profile-contract.md`

本文只澄清三件事：

- 本地三个入口 `feishu-codex`、`feishu-codexctl`、`fcodex` 的职责边界
- thread-wise profile 在本地和飞书侧分别怎么生效
- 为什么本地命令面现在统一使用 attach / detach，而不再对外暴露 release-runtime

## 1. 三个本地入口

### 1.1 `feishu-codex`

负责：

- 安装
- service 生命周期
- autostart
- 实例管理
- skill 安装等项目级辅助动作

不负责：

- 进入 Codex TUI
- 查看单个 binding / thread 的底层状态

### 1.2 `feishu-codexctl`

负责：

- 查看运行中的实例
- 查看目标实例的 service / binding / thread 状态
- 做有限的 binding / thread / image 管理动作

不负责：

- 进入 Codex TUI
- 直接改写上游线程内部历史

### 1.3 `fcodex`

负责：

- 恢复本地 live thread
- 进入 Codex TUI
- 作为本地独立 frontend 订阅 backend thread

它不是：

- 飞书命令面的镜像
- service 管理 CLI

## 2. 本地命令面的正式命名

当前对外正式命名应统一为：

- `service attach`
- `binding attach`
- `binding detach`
- `thread attach`
- `thread detach`

底层内部仍可能调用：

- `thread/unsubscribe`

但这只是服务内部协议实现，不再是用户概念。

## 3. profile 是 thread-wise，不是 binding-wise

这条规则在本地与飞书侧完全一致：

- 同一个 thread 无论从飞书还是 `fcodex` 恢复，都应看到同一个 thread-wise profile
- binding 只决定“当前会话记住哪个 thread”
- attach / detach 只决定“当前飞书会话收不收推送”

## 4. 本地如何改 profile

### 4.1 新线程

新线程可以通过：

- `fcodex -p <profile> new`
- 或飞书 `/new` 后再 `/profile <name>`

### 4.2 已有线程

已有线程的直接改写条件，以
`docs/contracts/thread-profile-semantics.zh-CN.md` 为准。

因此：

- `fcodex resume <thread> -p <profile>` 遇到 loaded thread 必须拒绝
- 不应要求用户先去理解 release-runtime / unsubscribe
- 推荐路径应是飞书 `/profile <name>`，必要时走 reset-backend

## 5. reset-backend 在本地与飞书侧的关系

无论从飞书还是本地 `feishu-codexctl service reset-backend` 触发：

- backend 会被重置
- binding bookmark 保留
- 相关 Feishu binding 变成 `detached`
- thread-wise profile/provider 保留

之后若想继续收到飞书推送，应显式选择：

- 当前线程 attach
- 当前实例 attach
- 保持 detached

## 6. 为什么不用 release-runtime 作为主文案

因为它把三层概念混在了一起：

- binding 是否还记得 thread
- 飞书是否还接收推送
- backend 是否还 loaded

当前更清晰的合同是：

- `binding`
- `attach / detach`
- `backend / live runtime`

这样本地与飞书侧可以共享同一套心智模型，而不必再让用户猜 “release 到底 release 了哪一层”。
