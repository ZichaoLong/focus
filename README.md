# feishu-codex

> 说明：本项目最开始来源于 [shenman9/feishu_bot](https://github.com/shenman9/feishu_bot)。更准确地说，它是从 `feishu_bot` 中用于“飞书 + Claude Code”的那部分子集能力演进而来，并在此基础上改造成面向 Codex 的实现，因此形成了当前的 `feishu-codex`。

`feishu-codex` 把飞书机器人、本地 `fcodex` 和同一个 `codex app-server`
接到一起。

本项目提供：

- 飞书里的 codex thread 使用入口
- 本地继续同一 codex live thread 的 `fcodex`
- 本地查看 / 管理面 `feishu-codexctl`

你可以把它理解成一层桥接：

- 飞书会话先绑定到某个 `thread`
- 这个 `thread` 跑在某个 `feishu-codex` 实例自己的 shared backend 即 `codex app-server` 上
- 多订阅观察+单交互轮转租约：飞书和 `fcodex` 可连到同一个实例 backend，此时可安全继续操作同一个 live thread，并同时收到回复消息推送
- 裸 `codex` 仍然可单独使用，裸 `codex` 将使用自己的独立 backend，不在共享线程合同内

## 使用入口

| 入口 | 作用 | 什么时候用 |
| --- | --- | --- |
| 飞书聊天命令 | 当前 chat binding 的使用入口 | 在飞书里提问、切线程、改当前会话设置 |
| `feishu-codex` | 配置、启停、卸载、登录后自动启动、实例管理 | 管理本地服务 |
| `fcodex` | 接到同一实例 shared backend 的本地 Codex 入口 | 想在本地继续飞书正在操作的同一 live thread |
| `feishu-codexctl` | 本地查看 / 管理面 | 看 binding / thread / service 状态，做 thread-scoped 管理 |

## 快速开始

### 前置条件

- Python 3.11+
- 本机已安装 `codex` CLI，且 `codex --help` 可正常执行
- 已在飞书开放平台创建应用，拿到 `app_id` 与 `app_secret`

### 1. 安装

macOS / Linux：

```bash
cd /path/to/feishu-codex
bash install.sh
```

Windows PowerShell：

```powershell
cd \path\to\feishu-codex
.\install.ps1
```

不要使用 `pip install .` 或 `pip install -e .`，这将安装无法被卸载命令 `feishu-codex uninstall/purge` 覆盖的残留命令入口。

### 2. 配置飞书应用

推荐先一次性配好权限、事件与回调。

#### 权限

权限用途概览

  - 初始化与机器人自识别: `/init`, `/bot-status`
      - `application:application:self_manage`
  - 用户与群成员身份识别: 群成员称呼, `/whoami` 身份信息获取
      - `contact:contact.base:readonly`
      - `contact:user.base:readonly`
      - `contact:user.employee_id:readonly`
  - 接收单聊与群聊消息
      - `im:message.p2p_msg:readonly`
      - `im:message.group_at_msg:readonly`
      - `im:message.group_msg`
  - 读取消息、发送回复、更新卡片
      - `im:message`
      - `im:message:readonly`
      - `im:message:send_as_bot`
      - `im:message:update`
  - 发送图片到飞书
      - `im:resource`

<details>
<summary>一键导入权限 JSON（点击展开）</summary>

在飞书开放平台「权限管理」页面点击「批量开通」，粘贴以下 JSON 即可导入当前建议权限集：

```json
{
  "scopes": {
    "tenant": [
      "application:application:self_manage",
      "contact:contact.base:readonly",
      "contact:user.base:readonly",
      "contact:user.employee_id:readonly",
      "im:message",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message:readonly",
      "im:message:send_as_bot",
      "im:message:update",
      "im:resource"
    ]
  }
}
```

</details>

#### 事件与回调

在「事件与回调」中启用：

- WebSocket 长连接模式
- 事件：`im.message.receive_v1`
- 回调：`card.action.trigger`

本项目默认走长连接，不需要公网 webhook URL。

### 3. 本地启动、配置、初始化

打开系统配置：

```bash
feishu-codex config system --open
```

按需写入 provider 环境变量：

```bash
feishu-codex config env --open
```

最小需要填的通常是：

- `system.yaml` 里的 `app_id`、`app_secret`
- `feishu-codex.env` 里的 provider key 或其他环境变量

启动服务：

```bash
feishu-codex start
```

如需登录后自动启动：

```bash
feishu-codex autostart enable
```

查看初始化口令：

```bash
feishu-codex config init-token
```

然后在飞书里私聊机器人：

```text
/init <token>
```

这一步会把当前发送者登记为管理员，并尝试写入当前机器人的 `bot_open_id`。
非管理员普通私聊默认不能直接使用机器人；但 `/whoami`、`/bot-status`、`/init <token>` 这类身份与初始化命令仍可在私聊使用。

### 4. 开始使用

在飞书里：

- 发送 `/help` 或 `/h` 看可用命令导航
- 发送 `/commands` 看可用命令列表
- 直接发送普通文本开始对话
- 手动发送命令 `/new`、`/resume`、`/profile`、`/cd` 管理当前会话绑定的 thread
- 如果想让同一个机器人同时服务多个项目，建议为每个项目单独建一个群聊；每个群聊固定在自己的目录和 thread 上，避免在单聊里反复 `/cd`、`/resume`
- 群聊里管理员先用 `/group activate` 激活，再按群模式使用

在本地继续同一个 live thread：

```bash
fcodex
fcodex resume <thread_id|thread_name>
fcodex --instance corp-a
```

本地查看 / 管理：

```bash
feishu-codexctl service status
feishu-codexctl binding list
feishu-codexctl thread list
feishu-codexctl thread status --thread-name <name>
feishu-codexctl image send --path ./diagram.png
```

### 5. 多机器人多实例

如果你希望配置多个飞书应用及机器人，每个机器人对应不同的 `feishu-codex` 实例，可按下面方式创建命名实例：

```bash
feishu-codex instance create corp-a
feishu-codex --instance corp-a config system --open
feishu-codex --instance corp-a start
fcodex --instance corp-a
```

每个实例有自己的：

- 配置目录
- 数据目录
- service
- shared backend

所有实例共享：

- `CODEX_HOME`
- 持久化 thread 命名空间
- 机器级 `ThreadRuntimeLease`

## 更多帮助

- 飞书里发送 `/help` 或 `/h`
- 本地查看 `feishu-codex --help`
- 本地查看 `feishu-codexctl --help`
- 深入文档看 `docs/doc-index.zh-CN.md`

## 一图看懂架构

```mermaid
flowchart LR
  subgraph Feishu["Feishu"]
    ChatA["单聊 / 群聊 A"]
    ChatB["单聊 / 群聊 B"]
  end

  CLI["feishu-codex<br/>安装 / 配置 / 启停 / 实例管理"]
  CTL["feishu-codexctl<br/>本地查看 / 管理"]
  TUI["fcodex<br/>本地继续同一 live thread<br/>local permissions"]
  Raw["裸 codex<br/>独立本地会话"]

  subgraph Instance["实例 explorer"]
    BindA["binding A<br/>binding-wise permissions"]
    BindB["binding B<br/>binding-wise permissions"]
    Service["feishu-codex service"]
    Backend["shared codex app-server"]
    Thread["thread<br/>thread-wise profile"]
  end

  Global["machine-global coordination<br/>ThreadRuntimeLease / instance registry"]

  ChatA --> BindA --> Service
  ChatB --> BindB --> Service
  Service --> Backend --> Thread
  TUI --> Backend
  CTL -.查看/管理.-> Service
  CLI -.安装/配置/启停.-> Service
  Global -.协调.-> Backend
  Raw -.不在共享线程合同内.-> Thread
```

这张图只表达 3 件事：

- 飞书会话先绑定 `thread`
- `fcodex` 连的是同一个实例 backend
- 裸 `codex` 不在共享线程合同内

## 一图看懂共享与冲突控制

```mermaid
flowchart LR
  subgraph A["实例 A：同一 live thread"]
    F1["Feishu binding 1<br/>(attached, own permissions)"]
    F2["Feishu binding 2<br/>(attached, own permissions)"]
    TUI["fcodex subscriber<br/>(local permissions)"]
    Thread["thread<br/>thread-wise profile"]
    Owner["interaction owner"]
  end

  subgraph B["实例 B"]
    Other["尝试 resume / attach<br/>同一 thread"]
  end

  Gate["cross-instance loaded gate"]
  Lease["ThreadRuntimeLease"]

  Thread -->|"普通输出广播"| F1
  Thread -->|"普通输出广播"| F2
  Thread -->|"普通输出广播"| TUI

  Owner -. "独占：下一轮写入 / 审批 / 补充输入 / 中断" .-> Thread

  Gate -. "先问其他运行中实例：<br/>这个 thread 是否仍 loaded" .-> Thread
  Lease -. "loaded gate 通过后，原子 claim：<br/>同一时刻只允许一个实例 live continuation" .-> Thread
  Other -. "跨实例 attach / resume" .-> Gate
  Gate -. "通过后再拿" .-> Lease
```

这张图表达的是当前运行时合同：

- 多个 `attached` 订阅者可以同时收到同一 thread 的 backend 普通消息
- 多订阅不等于多方都能写；真正的写入与交互控制由 `interaction owner` 独占
- 跨实例 attach / resume 会先过 `loaded gate`；若别的运行中实例仍把该 thread 保持为 `loaded`，就直接拒绝
- 只有 `loaded gate` 通过后，才会继续争抢机器级 `ThreadRuntimeLease`

**补充说明**
- `permissions` 不是 thread-wise next-load 设置。飞书会话和本地 `fcodex` 各自保存自己的权限设置，彼此不会自动同步；由发起 `thread/start` / `turn/start` 的那一端写进 app-server
- `model` 也不是 thread-wise next-load 设置。飞书 `/model` 只覆盖当前会话后续 turn 的 `model` 名称；不改 thread-wise `profile / model_provider`
- `profile`、`memory` 才是 thread-wise next-load 设置；切换它们通常要先让该 thread 回到未加载状态，必要时执行 `reset-backend`
