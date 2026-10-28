# HTML 报告与演示预览验证（2026-10-28）

本记录描述自包含 HTML 预览的实现与本地验证，不替代
[单文件下载与预览合同](../contracts/focus-web-file-download.zh-CN.md)。源码基线为
`394d7505f45403f9ebea87de2ac858551329dea8`，本次 wire 从 v34 更新为 v35。

## 实现范围

- 复用 Focus 现有 Web 服务、认证与单文件传输，不增加服务进程、端口、运行依赖或持久数据。
- HTML 独立限额 8 MiB；完整源码和交互视图共用一次读取，可切换、刷新、复制、下载和全屏。
- 固定且需要认证的引导页使用专用 CSP 和无同源权限的 iframe；主应用 CSP 不变。
  私有 MessagePort 只交付源码、渲染状态及真实用户点击的本地引用，不把文件读取结果交回报告。
- 本地出处使用报告的解析后目录，保留行号或章节。Markdown 章节按标题定位；文件预览关闭节点
  虚拟化以便定位尚未进入视口的标题，仍受原有 128 KiB 渲染上限约束，会话渲染保持原行为。
- 从工具栏全屏打开下载先退出全屏；取消下载回到原报告，保留报告内部步骤。

## 浏览器证据

`web/test/html-preview-browser.test.ts` 使用真实 Vue 文件弹窗和预览组件，直接读取后端引导页
与 CSP 常量；HTTP 传输在浏览器测试中被替身接管。真实网关的认证、响应头、query 和代理 audience
另由后端 HTTP 测试覆盖，未连接或更新现有运行实例。

浏览器验证覆盖：

- 报告脚本、SVG、步骤交互、hash 更新、原生 dialog、报告自身全屏及 Focus 工具栏全屏；
- 源码切换不重复读取文件，刷新重新读取；等待刷新期间旧 iframe 已销毁，关闭后迟到结果不重开；
- 无法读取 parent DOM、Cookie 和 localStorage；普通伪造 postMessage 与脚本 `.click()` 不打开本地文件；
- 外部脚本／图片被 CSP 阻止并显示说明，401 引导失败仍可查看已读取源码；
- 本地引用保留 cwd、百分号编码、中文路径及章节；下载取消保留报告步骤。

仓库回归使用独立编写的通用 HTML fixture，不依赖外部工作区或个人文件。额外参考文件的本地验收
记录不纳入仓库。没有 iOS／Android 实机或 Safari／Firefox 验收证据。

## 本地门禁

环境：Linux，Python 3.11.15，Node 25.9.0，Google Chrome 156.0.8078.47，依赖锁 resolver 为 uv 0.8.14。
远端 Web CI 使用 Node 22，本地结果不能替代对应提交的远端结果。

| 检查 | 结果 | 证据与范围 |
| --- | --- | --- |
| `focus-web-file-download` 固定验证锥 | passed | 后端 81 项、Web 146 项及相关 guard |
| Python 全量 | passed | 4,143 项；6 条既有依赖／测试告警 |
| Web 全量 | passed | 126 个测试文件、1,378 项 |
| HTML 浏览器专项 | passed | 4 项，覆盖隔离、交互、失败与销毁 |
| Python lint／compile、依赖方向、import cycle、source context | passed | source context 仍有既有 review 提示 |
| Web 类型、依赖方向、wire 生成一致性 | passed | 无类型或方向违规 |
| style／Kimi provenance／third-party notices | passed | style 有 17 条 baseline 提示；provenance 分类包含新增文件 |
| Python lock replay | passed | uv 0.8.14 重解析后两份 lock 无差异 |
| production build | passed | 有既有大 chunk 提示，未增加运行依赖 |
| 两次 install bundle build | passed | 验证构建得到的 ZIP 逐字节一致，没有安装或发布 |
| 文档与导航闭环 | passed | 正式中英文合同、wire 与 capability refs 同步；仅本次源码的副本文档检查通过 |
| 安装、发布、更新现有实例 | not-run | 本次只实现、提交和推送 |

整个工作区的文档检查还报告一份原有、未跟踪的 daemon 评估材料未进入索引；本次没有修改、暂存
或补登该材料。上述文档通过结果来自排除该材料的源码副本。远端 CI 与 Docs 须在推送后按精确提交
SHA 读取，本文的本地门禁不预先宣称远端成功。

## 已知限制

- 这是自包含文件预览，CDN、同目录 CSS／JS／图片、模块导入、后端 API、存储及开发服务器不在范围内。
- 沙箱限制 Focus 权限，不提供 CPU／内存配额。审查实测确认脚本仍可导航自身 iframe，因此不能把
  CSP 描述成阻断恶意 HTML 一切出站请求的离线环境；父页面与凭据读取仍受同源隔离限制。
- 报告自身状态不跨刷新保存；字体、触摸及全屏取决于客户端浏览器，固定画布在手机竖屏上可能不易阅读。
- 章节定位支持标题 ID 与常见小写连字符 slug，不保证所有站点／Markdown 方言的锚点规则；无法定位会提示。
- 服务与静态资源需一起部署为 wire v35；源码推送不会更新已经运行的 Focus 实例。
