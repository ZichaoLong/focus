# Focus Web 问答打印与 PDF 保存合同

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-summary-print.md`。

## 范围与入口

桌面会话菜单、侧栏会话菜单、窄屏顶部导出菜单和窄屏会话切换菜单，在既有
`export` capability 可用时，同时提供“导出问答 Markdown”和“打印／另存为 PDF”。
打印操作与 Markdown、线程数据导出共用正在导出的互斥状态。

`createFocusThreadActions` 通过现有 authenticated `exportThreadSummary` 取得完整
Markdown；内容与边界由 [Web wire 合同](focus-web-wire.zh-CN.md) 的
`GET /api/threads/{thread_id}/export-summary` 定义。不得从聊天 DOM、已加载窗口或
阅读模式截取导出内容，也不得改变问答导出对工具过程、reasoning 和非文本附件的排除。
不新增 PDF endpoint、服务端浏览器依赖、外部转换服务或 wire DTO。

## 完整性与渲染

`SummaryPrintApp.vue` 是独立打印文档；`summaryPrintMarkdown.ts` 负责静态渲染，
`summaryPrintPreparation.ts` 负责图示、图片和字体准备。预览必须呈现整份导出，不使用
聊天虚拟化、渐进批次、代码折叠或 diff 头尾截取。代码保留全部行并允许换行和跨页；
表格允许单元格换行、跨页并重复表头。原生打印布局隐藏界面控件和使用说明。

中文标点附近的加粗识别与粗体字体回退复用[正文渲染合同](focus-web-markdown-rendering.zh-CN.md)。

- 公式复用 `markdownMath.ts` 的 exact grammar：同一行闭合的 `\(...\)`，块位置的
  `\[...\]` 或 `$$...$$`。不猜测单美元、未闭合或正文中的块公式。未识别内容按
  文字保留，KaTeX 失败时保留含定界符的源码。KaTeX 禁止 trusted HTML/URL 扩展。
- Markdown 原生 HTML 不执行。代码与失败源码必须转义；Markdown 链接沿用解析器的
  安全 URL 校验。图片只尝试 HTTP(S) 或内嵌常见栅格格式，不读取本机路径或为图片
  额外附加 Focus 认证请求头；受站点 CSP 限制或加载失败时显示其 Markdown 地址与替代文字。
- Mermaid 使用已有依赖的 strict 模式并清洗 SVG；失败时保留完整围栏内容。
- 图片与字体有有界等待，准备失败须保留源码或地址并提示用户检查预览；顶层解析或
  准备异常回退整份原始 Markdown。完整导出读取失败时显示失败状态，不启用打印按钮。

## 打印与生命周期

`summaryPrintWindow.ts` 在点击事件内同步打开同源 `?print=summary` 页面，以避免
异步读取后才打开窗口造成拦截。弹窗被拦截时提示允许本站弹窗再重试，并不启动导出。
预览只接收 exact opener、origin 和一次性 rendezvous ID 匹配的内容；发送方也校验
exact child、origin 与 ID。内容只在内存传递，不写入 URL、localStorage 或服务端文件。
页面 URL 不携带会话正文或认证参数。传递成功后移除监听并断开 opener；关闭、超时
或读取失败有明确清理/失败路径。刷新、独立打开或分享预览 URL 不恢复内容。

打印入口不会挂载 `FocusApp` 或注册第二个 active document。预览取得内容前应保留原
标签页，取得后可以独立预览并反复打印。只有渲染和资源准备完毕才启用打印按钮。

按钮调用原生 `window.print()`，浏览器决定打印、保存 PDF、纸张、缩放和页眉页脚。
不得把函数返回或 `afterprint` 当作文件已保存的证据；取消后可再次打印。页面提供
桌面“另存为 PDF”、Android Chrome“分享 → 打印”与 iPhone Safari“分享 → 标记”
的使用提示。实际菜单随系统和浏览器版本变化，不承诺手机浏览器都支持一键下载。
宽表格、超长公式可由用户调整横向纸张或缩放；不同字体和浏览器不保证像素一致。

## 验证边界

单元测试验证完整代码、公式语法与回退、安全转义、完整导出调用、弹窗拦截、互斥、
同源传递与失败清理。浏览器验证覆盖宽/窄屏菜单、独立预览、实际 PDF 的分页与文本、
取消后重试、Markdown 下载和导出失败。桌面 Chromium 与窄屏模拟不能替代真机 Safari、
Android Chrome 的系统保存流程验证。
