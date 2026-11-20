# Focus 移动容器

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-mobile.md`。

## 入口与认证

每个入口保存名称、站点 origin、随机实例 ID 和可选的网页登录方式。每次只选中一个实例，只有选中的实例维持业务订阅。
远端根地址从系统信任的 TLS 链加载。本地 Focus 授权另接受手机回环 HTTP（仅 `localhost`、`127.0.0.1`、`[::1]`），Basic 凭据仅在 HTTPS 上使用。原生 Basic 认证使用单独的无脚本顶层 GET `/focus-connect.txt`，
阻止子资源及重定向携带新凭据。只有配置的 HTTPS 站点和实际挑战的 Basic realm 均匹配才响应。
浏览器引擎在同一保护空间内处理随后请求和 WebSocket Upgrade。重试失败须由用户更新，超时保留原凭据。
本版支持整个入口共用 Basic 保护空间。页面运行期间遇到新的挑战时可以重新验证入口。
Focus 的 cookie、注册、可信代理证明和 mutation admission 继续遵循外部访问和 wire 合同。

## 宿主协议 v1

入口的 `focusApp` 查询参数只让根页面短暂等待协商。原生在配置 origin 的顶层根文档检测
`meta[name=focus-mobile-contract][content="1"]`，注入本 document 的随机 ticket、实例 ID、版本和能力列表，
并发送 `focus-host-ready`。未知版本和无协商的页面使用浏览器默认行为。

- `wake` 表示可接收 `focus-host-resume` 和 `focus-host-pause`。前台信号触发现有连接检查，后台信号刷新草稿与阅读锚点。
- `thread` 允许根页面通过带 ticket 的 `thread` 操作提交最近的线程定位提示（至多 256 个字符，空串表示工作区）。壳在下次打开时把它编码为根页面的 `thread` 查询参数，Web 仍须经现有入口向服务端确认该线程。
- `resume` 表示整个实例只有一个可恢复的浏览窗口。Web 保存 client hint、GET locator、原 writer 的恢复记录、最近一次已确认的线程、文字草稿及最近已确认线程的阅读模式与位置。
  新 document 必须重新注册。文字和可验证阅读锚点按实例及当前已确认的线程或工作区恢复，附件、审批 capability 与发送 scope 仍属于服务端签发的 writer。
  已协商恢复的 Web 页面在可用时用按实例隔离的 IndexedDB 严格持久事务记录文字草稿、模式和阅读锚点，初始化时迁移本地旧记录，清理草稿同步删除持久副本。请求记录及附件凭据沿用各自原有存储。
- `tabs` 提供可选的显示名 `name`。根页面使用带 ticket 的 `instances` 打开实例列表，用 `chrome(web|native)` 指示实例入口是否已由网页呈现。加载、访问异常及未协商版本保留原生入口。
  切走时宿主在顶层调用 `__focusSetTabActive(false)`。Web 刷新草稿和阅读锚点、关闭 socket 并停用轮询和重试。只有收到 `true` 才可保留该文档。管理实例可设置最近保留 1 至 5 页，默认 2 页，含当前页，每实例一页。超出上限或调低设置时先释放最久未使用的页面。回到实例调用 `__focusSetTabActive(true)`，经原有握手和状态重读恢复。无确认、内存回收及手动重新连接均可重建页面。
- `save` 使用 `prompt("focus/1/<ticket>/<op>", value)` 在两个引擎内等待系统选择或写入结果。
  `choose` 只接受文件名，系统选择目标。`write` 携带最多 24 KiB 原始字节的 Base64，逐块确认后发下一块。
  `finish` 从临时文件写入选定目标，`abort` 释放暂存。成功返回 `ok`，取消或失败使 Web 停止写入。
  正文由现有带会话的 Web 请求读取。普通 HTML 上传沿用系统文件选择器和原 Web 上传路径。
- `print` 接收一次带 ticket 的打印请求及不超过 255 字符的任务名。Web 只呈现已准备好的完整问答打印预览，原生把当前网页交给系统打印面板。正文留在当前 document 的内存中。
- `navigation` 让已协商的顶层文档把用户实际点击的跨站 HTTPS 内容链接交给带 ticket 的 `external` 操作。壳复核地址、拒绝嵌入用户名密码，在原页面上方按需打开独立的网页容器，显示当前站点并提供交给浏览器的入口。外链页无 Focus 桥接、实例凭据和实例浏览数据。Android 使用单独进程与数据目录，ArkWeb 使用临时浏览上下文。系统返回一次关闭整次外链浏览。入口的跨站登录回跳仍在实例自己的 WebView 中进行，遵守该条目的 SSO 选择。
- 系统界面、原生抽屉及外链页优先处理返回。在活动的 Focus 根文档，壳核对当前 ticket 后调用 `__focusBack()`。Web 同步报告是否接手，一次只处理最上层。文件预览调用已有的上一文件或取消动作，首个文件关闭后回到对话。根页面报告没有可退内容时，整个 App 退后台，保留所选实例。缺少协商回调时优先退网页历史，随后退后台。文档已换、切换实例和不确定的异步回执不能触发第二次后退。普通浏览器继续使用自身导航。

顶层导航和销毁撤销 ticket。暂存的页面在未选中期间不能使用 ticket，重新选中同一文档才恢复。外部网页和沙箱 HTML 预览均不获得桥接。
外链地址仅供独立容器浏览。协议不接受任意带凭据的请求、目标路径、代码或业务重发。推送登记和通知权限需要另行协商。

## 实例抽屉和 Android 分发

协商 `drawer` 的宿主接受 `instances` 的明暗主题提示，使用本地注册表覆盖显示实例抽屉。打开、取消、选择当前项均保持当前文档活动。切换到另一项时才执行停放和确认。在普通与阅读顶栏使用独立入口。从对话进入管理后，「返回对话」和系统返回键均可重新选中原实例。纯改名保留原文档；更换地址或删除原实例后回到列表选择。网页只获得所选实例的名字。加载失败或缺少桥接时保留原生入口。

Android 宿主另提供 `android-update`。用户在抽屉选「关于 Focus Mobile」时触发可取消事件 `focus-host-about`。顶层文档使用 ticket 请求 `apk-info` 获取已安装版本和摘要；`apk-begin` 提交已选清单，`apk-write` 每块至多 24 KiB，`apk-finish` 验证完整性、包名、版本和当前证书或有效轮换链，再由用户确认交给系统安装器。`apk-abort` 或页面离开清理临时传输。`apk-save` 对已接收的 APK 执行相同校验，经系统选择器另存文件供手动安装。

发布方为明确指定的 Android 渠道发包。源码集成与服务端 stable Release 各自独立。移动分发 Git 仓库的 main 分支在同一提交中包含 `channels/{main|stable}.json` 和 `android/<sha256>.apk`。清单字段为包名 package、版本 version、Android version_code、40 位源码 source_revision、sha256、certificate_sha256 和 size（最多 32 MiB）。APK 内嵌精确源码 revision。发布工具核对 APK 与预期发布证书、版本和源码，远端推送后从独立 Git 对象库读回验签。晋级可复用同一包，普通提交或 CI 不移动渠道。直装版本号可相等；回切还要求安装器允许覆盖及应用数据兼容。

服务端读取独立的 `FOCUS_MOBILE_DIST_URL`（HTTPS 或 SSH Git URL），默认 `https://github.com/ZichaoLong/focus-mobile-dist.git`。已认证、带 CSRF 和文档身份的 `POST /api/mobile/android/{channel}/check` 接受空对象，按需同步，返回 release、checked_at、stale。未发布渠道返回空 release。网络中断时标记最后成功缓存；不将损坏内容提升为当前版本。缓存按发布源隔离在 Focus 数据目录的 mobile-updates 下，独立于服务端安装事务。已认证的 `GET /api/mobile/android/apk/{digest}` 从该源返回确切缓存文件。手机端不向 Git 源发请求；向安装器只授予私有缓存中已校验 APK 的临时读权限。签名密钥属于发布端。

## 使用与验收

[构建、安装和验证](../../mobile/README.md)
