# Focus Web 单文件下载

文档角色：中文规范源。英文同步副本：`docs/contracts/focus-web-file-download.md`。

## 访问与文件内容

已认证的 Focus Web session 可以下载 Focus 服务进程能够读取的普通文件。这里沿用实例的
完全信任协作者模型，不增加工作区白名单、逐文件审批或用户 ACL。工作区仅用于解释相对路径。
符号链接可解析到工作区外；目录、设备、管道等非普通文件不提供下载。此功能不提供目录树、
文件编辑、压缩打包或文件／媒体预览。

- `GET /api/files/info?path=...&cwd=...` 校验路径、文件类型和可读性，返回 exact
  `FocusFileInfo={path,name,size}`，其中 path 为解析后的服务器绝对路径、name 为文件名、size 为
  非负字节数。仅检查元数据和打开权限，不读取正文。相对路径需要绝对 cwd；`~` 按服务端账号展开。
- `GET /api/files/download?path=...&filename=...` 接受绝对路径，可选 filename 仅建议客户端保存名。
  不需要浏览器 document 或 writer authority，因此普通浏览器下载可以使用 session cookie，
  不把 token 放进 URL。两个 endpoint 都经过既有 Host、session、trusted-proxy audience 准入，
  不续期 session，不调用 app-server 或 RuntimeLoop。
- 两条 query 拒绝未知、重复字段、空 path 与 NUL。文件缺失、不可读、非普通文件或无法解析
  分别显式失败。失败响应不携 attachment header。
- 下载使用 `application/octet-stream`、`Content-Disposition: attachment`、`Cache-Control: no-store`。
  基于已有 aiohttp FileResponse 的有界文件传输与 HTTP Range 行为，禁用静态资产的同名 `.gz/.br`
  替换，不把整个文件读入服务端或页面内存，不增加运行依赖。
- 下载取得本次读取的文件，不是回复生成时的历史副本。信息查询与下载之间可发生文件变动；
  下载重新校验文件。正在原地写入的文件不提供快照一致性，HTTP Range 也不保证跨版本续传。

## 链接与保存体验

`Markdown.vue` 的本地链接委托给 Focus 文件下载弹窗；外部 URL 和 Mermaid SVG 内的链接保持
原语义。显式 Markdown 链接在流式输出时也可点击；普通文本中的自动路径识别仍等待输出稳定。
本地 URI／百分号编码、绝对／相对路径与常见行号引用被转换为文件路径，行号不成为文件名。
相对路径的 cwd 来自打开链接时的会话；网络等待和后续切换会话不能重定向下载目标。
本地图片引用同样显示显式文件下载链接，不自动读取或嵌入图片；未提供文件操作回调的消费者
仍保留原有不可用提示。

点击链接只加载文件信息。弹窗显示服务器路径、大小、可编辑的保存文件名与实际保存名称，
按浏览器能力显示“另存为”或“下载”；关闭弹窗取消页面拥有的请求和写入。

- 系统保存窗口复用 `browserFileSave.ts`，在确认手势内、正文读取前调用 `showSaveFilePicker`。
  用户取消即结束。调用因 SecurityError／NotSupportedError 不可用时，改为明确显示普通下载说明，
  需要用户再次点击，不自动另下载一份。
- 原生保存按响应流分块写入，展示已接收字节数，写入和关闭均成功才提示保存完成。取消或失败
  尝试 abort staged writes，不回退为另一份下载；不自动删除用户选中的文件。系统窗口可能已创建空文件。
- 不支持系统保存窗口时，点击下载先复查文件可用性，再交给浏览器原生下载管理，避免完整 Blob。
  保存目录遵循浏览器设置；Focus 只提示“已交给浏览器”，不声称文件已保存。交接后的进度／取消由
  浏览器拥有。错误若发生在复查之后，由浏览器处理，错误页在独立标签页中，不替换会话。
- 路径、句柄和下载状态不持久化；不存在自动预取正文或自动预览。保存文件名按可移植字符与
  UTF-8 字节预算处理，保留文件扩展名，不修改服务器文件。

既有 Markdown／JSONL 导出只复用系统保存窗口的选择规则，继续按
[导出文件名合同](focus-web-export-filenames.zh-CN.md)保持完整 Blob、命名、独立文档标题、取消
与回退行为；PDF 打印流程不变。
