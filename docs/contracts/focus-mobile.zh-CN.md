# Focus 移动容器

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-mobile.md`。

## 入口与认证

每个入口保存名称、站点 origin、随机实例 ID 和可选的网页登录方式。每次只有一个业务页面。
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
- `resume` 表示整个实例只有一个可恢复的浏览窗口。Web 保存 client hint、GET locator、原 writer 的恢复记录、最近线程及文字草稿。
  新 document 必须重新注册。文字和可验证阅读锚点按实例及当前已确认的线程或工作区恢复，附件、审批 capability 与发送 scope 仍属于服务端签发的 writer。
- `save` 使用 `prompt("focus/1/<ticket>/<op>", value)` 在两个引擎内等待系统选择或写入结果。
  `choose` 只接受文件名，系统选择目标。`write` 携带最多 24 KiB 原始字节的 Base64，逐块确认后发下一块。
  `finish` 从临时文件写入选定目标，`abort` 释放暂存。成功返回 `ok`，取消或失败使 Web 停止写入。
  正文由现有带会话的 Web 请求读取。普通 HTML 上传沿用系统文件选择器和原 Web 上传路径。
- `print` 接收一次带 ticket 的打印请求及不超过 255 字符的任务名。Web 只呈现已准备好的完整问答打印预览，原生把当前网页交给系统打印面板。正文留在当前 document 的内存中。

导航、切换实例和销毁页面撤销旧 ticket。外部网页和沙箱 HTML 预览均不获得桥接。
协议不接受任意 URL、目标路径、代码或请求重发。推送登记、通知权限和安装包更新需要另行设计和协商。

## 使用与验收

[构建、安装和验证](../../mobile/README.md)
