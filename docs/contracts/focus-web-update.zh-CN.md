# Focus Web 浏览器更新合同

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-update.md`。

本文定义浏览器更新 Focus 安装面的来源、预检、确认和重启边界。它不把更新
实现成进程内 hot replacement，也不更新 Codex app-server/CLI。

## 1. 更新源与输入

- 更新源是 machine-level durable 配置，默认
  `https://github.com/ZichaoLong/focus.git`，分支固定为 `main`。
- 浏览器不能提交 workspace 路径、shell 命令或本地文件路径；Git URL 只接受
  HTTPS/SSH 形式，凭据由部署机器的 Git credential helper、deploy key 或 SSH
  agent 提供。
- 修改更新源必须显式确认；每次检查都重新填写 commit。commit 留空时先读取
  远程 `refs/heads/main`，随后固定为完整 40 位 SHA，构建期间不得重新解析
  `main`。

## 2. 检查与预检

`POST /api/update/check` 只创建一个有界的后台检查操作，不改变当前安装或
service。操作会在临时目录 clone/fetch 精确 commit、构建 Web production assets
和 local bundle，并在停服前完成：

- Git、Node/npm 与 Python 可用性以及 package index、代理、证书的实际请求；
- staging 受管环境中的 pip 安装和 `pip check`；
- 下载完整 wheelhouse 并记录文件清单，使应用阶段使用 `--no-index` 离线安装，
  不会在停服后意外发起第二次网络请求；
- 目标文件系统的可用字节、inode、临时目录和 bundle staging 空间；
- bundle 中的 Focus wheel、依赖锁和 source revision 一致性。

独立 updater 会继承部署用户明确配置的 Git/SSH、HTTP(S)/SOCKS 代理、pip/npm
index 与证书环境，以及 Focus 根目录；不会把 provider/API 凭据等任意 service 环境
转发给 source-controlled build hook。预检因此使用与该部署用户安装相同的网络与依赖
来源。

失败时 operation 为 `failed`，旧服务继续运行。成功时 operation 为 `ready`，
只保留一个精确 commit 的 staging 结果，不接受隐式 fallback。

## 3. 应用、重启与结果

`POST /api/update/apply` 必须携带 ready operation id，并由用户再次确认。在 Linux
上 Focus 以独立的 systemd user transient unit 启动可信 updater；其他平台在停服前
明确拒绝应用。该 updater 由既有 managed install transaction 证明所有实例 idle，
关闭 ingress，停服，安装已验证 bundle，再启动原先运行的实例并等待 service 状态。
更新会影响本机所有 Focus 实例。

预检失败不会停服。停服后安装或启动失败不会自动回滚，也不会自动重试 unknown；
operation 会记录 `failed` 或 `unknown`，已停止的 service 可能保持离线，操作者需
检查 service 状态后手工处理。成功后 operation 记录 `succeeded`，浏览器必须在
service 恢复后完整 reload document，才能使用新的静态资源。

## 4. Wire 与生命周期

`GET /api/update` 返回 machine-level source 与当前 operation journal；source、
check、apply 都是 authenticated same-origin、CSRF 保护的用户动作，并续期当前
Web session。journal 不授予 thread、writer、approval 或 recovery authority；
更新期间连接断开只是 service lifecycle 的结果，不得把断线当作安装成功。

## 5. 维护闭环

更新来源、状态词汇、预检边界或安装事务变更时，必须同步更新本合同、英文 peer、
wire catalog/generated projection、Gateway、browser decoder/UI 和 focused tests。
