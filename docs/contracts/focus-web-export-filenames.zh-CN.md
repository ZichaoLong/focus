# Focus Web 导出文件名合同

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-export-filenames.md`。

## 命名与下载

浏览器的问答 Markdown 和当前线程 JSONL 导出，在读取完整内容前显示文件名输入框。
`FocusThreadActions.vue` 负责弹窗、选中会话标题的查找与取消；`createFocusThreadActions`
负责固定导出目标、导出互斥和 Blob 下载；`exportFilename.ts` 统一提供建议名与名称处理。
默认名称取点击时目标会话的标题，包括侧栏中非当前会话；无可用名称时回退到
`codex-conversation-summary.md` 或 `codex-thread-data.jsonl`。

- 输入框显示完整文件名，自动补全当前格式的扩展名，重复的同格式扩展名合并。
  名称处理采用 Unicode NFC，替换路径分隔符、不可用字符与控制字符，移除边缘点号和
  空格，避开 Windows 设备保留名，并按 Unicode 码点截断，使完整名称不超过 200 个
  UTF-8 字节。输入框下方始终显示实际交给浏览器的名称；空名称不能确认。
- 点击取消、关闭、遮罩或 Escape，以及承载组件卸载，均取消待命名请求；不读取或下载
  导出内容。不持久化用户输入的名称，不将其发送到服务端或放入 URL。
- 弹窗打开和导出期间，Markdown、JSONL 与打印共用互斥；确认后再次检查客户端的
  导出状态。目标线程 ID 与建议名在等待前固定，导航变化不能重新指向其他会话。
- 确认后仍通过原有 authenticated API 读取完整 Blob；自定义名称仅用于浏览器
  `download` 属性，不改写 Markdown 标题、问答正文或 JSONL 数据，也不改变 endpoint
  的 `Content-Disposition` 默认名称。内容范围仍由 [Web wire 合同](focus-web-wire.zh-CN.md)定义。

浏览器掌握最终保存名称与位置，可能进一步调整非法字符或为重名文件添加序号。
不依赖 `showSaveFilePicker`，不新增后端或部署依赖。

## PDF 建议名

打印入口不增加命名弹窗，仍在点击时同步打开预览。目标会话生成的 `.pdf` 建议名和完整
Markdown 一起在内存传递；打印页以不含扩展名的建议名设置 `document.title`，供浏览器
选择默认保存名称。它不改写预览的正文标题，也不承诺浏览器一定采用该名称；用户可在
系统保存界面修改名称。生命周期和设备限制遵循[问答打印合同](focus-web-summary-print.zh-CN.md)。
