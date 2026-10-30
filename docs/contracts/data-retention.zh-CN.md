# Focus 数据清理

文档角色：中文规范源。英文同步副本：`docs/contracts/data-retention.md`。

## 1. 管理入口与边界

Focus Web 的设置页提供三个控件：**Focus 记录保留期**、**附件保留期**、**立即清理过期数据**。
两个保留期独立选择 7 / 30 / 90 天，默认均为 30 天，按实例保存，无需重启。
唯一配置源是该实例的 `codex.yaml`：

```yaml
records_retention_days: 30
attachments_retention_days: 30
```

没有 Web 时使用以下命令，均支持单个 `--instance <name>`，实例选择沿用 focusctl 规则：

```bash
focusctl data status
focusctl data retention --records-days 30 --attachments-days 30
focusctl data prune
```

`status` 显示有效保留期和配置路径；`retention` 可只传一个周期，另一个不变，二者停服时也可使用。
Web、CLI 与手工修改 YAML 使用同一份配置；设置读取、自动和手动清理会重新读取，不需要重启。
`prune` 通过已认证的本机 control plane 请求运行中的 Focus 服务，完全不依赖 Web。
停服或控制面不可用时返回错误，不在 CLI 进程自行删除历史。CLI 只清理服务端数据；浏览器本地数据由浏览器处理。
清理完成返回 0，部分 owner 失败返回 1，参数/配置/服务错误或请求结果未知返回 2；结果未知时不自动重试。
Web 的立即清理执行同一到期规则；不是清空所有数据。显示服务端与当前浏览器的清理项数，部分失败明确提示。
自动清理每 30 分钟运行，首轮在服务启动后 30 分钟；诊断日志另沿用启动时清理。
浏览器在取得服务器当前策略后、每 30 分钟及手动清理时执行本地清理；其他浏览器在各自下次打开后处理。
设置打开时刷新策略。缩短保留期在下一次清理生效，延长保留期不会恢复已经删除的数据。

这两个设置覆盖可按年龄删除的 Focus 自管历史，不取代所有数据各自的生命周期。
Codex 线程数据仍仅通过 Codex archive/delete 接口管理。配置、绑定、群激活与上下文边界、偏好、
认证会话、lease、运行中操作、未知结果恢复凭据不按上述保留期删除。
飞书失联已完成凭据继续最多 4096 条；pending 凭据继续重试。系统 journal、用户生成的工作区文件、
历史工作区附件不纳入新的附件保留策略。

`focusctl purge` 仍是卸载并删除经过验证的机器级 Focus config/data 根目录，因而包括新附件缓存，
不删除浏览器数据、Codex 数据或工作目录中的历史附件。`focusctl logs status` 展示当前记录保留期，
`logs prune` 默认使用该周期；显式 `--keep-days` 只覆盖该次诊断日志清理。

## 2. 原规则与新规则

| 数据 | 原规则 | 新规则与计时依据 |
| --- | --- | --- |
| Focus 诊断日志 | 固定 30 天，另有容量轮转 | 记录保留期，按文件最后写入时间；容量和当前日志保护不变 |
| 群消息日志 | 无年龄清理 | 记录保留期，按消息 `created_at`；保护运行中的群、激活和边界状态 |
| 终态回复明细 | 无年龄清理 | 记录保留期，按 `recorded_at` |
| 图片投递明细 | 无年龄清理 | 记录保留期，按 `delivered_at`；不删除生成图片原文件 |
| 浏览器导航服务端记录 | 无年龄清理 | 记录保留期，按 `updated_at`；在线文档续期 |
| 浏览器输入历史 | 每个 scope 最多 100 条，无年龄清理 | 每条输入保存时间加记录保留期，100 条上限保留 |
| 浏览器草稿 | 发送或清空时删除 | 记录保留期，按最后保存/编辑活动；挂载中的草稿受保护 |
| 服务端提交诊断 | 已关联项随明确 Web 线程删除；未关联项 90 天 | 全部按记录保留期及最后诊断更新；活跃 trace 受保护，线程删除仍立即清理 |
| 浏览器提交诊断 | 最多 64 条 | 提交时间加记录保留期，64 条上限保留；在途提交受保护 |
| 已提交 Web 附件及媒体预览副本 | 30 天、512 MiB / 1024 文件 | 附件保留期；容量上限与新飞书附件共用，可能提前淘汰 |
| 新的已消费飞书附件 | 留在各 cwd，没有年龄清理 | 同一私有附件缓存和附件保留期 |
| 尚未消费的附件 | `attachment_ttl_seconds`，默认 1800 秒 | 保持原 TTL，不随两个档位改变 |

保留期是删除资格，不承诺准时删除。活动工作区中的已提交附件、在途文件 pin 暂缓物理清理；
容量在统一清理时检查，也避开活动工作区及刚提交的文件，因此使用中可暂时超过限额。删除先提交元数据，再清理字节。
没有合法时间戳的群日志行保留，不以文件时间猜测；损坏的单个 owner 返回失败，不阻断其他 owner。

## 3. 唯一 owner、持久化与重启

`CodexConfig` 定义 `records_retention_days`、`attachments_retention_days` 的严格 schema，
`DataRetentionStore` 是这两个 YAML 字段的读写 owner，API/CLI 中的 `records_days,attachments_days` 只是投影。
缺失字段使用默认值；损坏 YAML 或非法值不覆盖、不授权自动删除。跨进程 `codex.yaml.lock` 与私有原子写入
防止 Web/CLI 部分更新相互丢失；更新保留其他显式配置值，重新序列化 YAML mapping，不承诺保留注释和排版。
不保留第二份策略文件或长期内存副本；删除某字段会在下一次读取时恢复该字段默认值。

旧实例的 `data_retention.json`（schema 1）在首次访问设置时自动迁移：只补入 YAML 尚未显式设置的字段，
先原子提交 YAML，再删除旧 JSON。迁移中断可安全重试；两个 YAML 字段均已明确时，它们是提交检查点，
过时甚至损坏的 JSON 都不得覆盖，直接移除旧文件。仍需补入字段但旧 JSON 损坏/未知 schema 时，拒绝迁移与清理，
保留原文件供修复；不影响基本对话启动。用户通过 CLI 明确重设两个周期时，无需从旧文件推导值，可直接提交 YAML 并移除损坏旧文件。
迁移完成后不再读取或写入 JSON。首次 status/日志策略读取也可能触发该次迁移。

`DataRetentionService` 串行化服务内策略更新/清理并持有周期 worker；各数据仍由原 store 删除。
Web、CLI 和自动清理使用同一 service owner，服务 ingress receipt 覆盖整次清理；control request 不在 RuntimeLoop 上
执行阻塞文件操作。停服/离线 maintenance 拒绝新的清理；退出先停止 worker，未证明 join 时不能释放服务 authority。

`AttachmentStore` 是两个入口共享的唯一文件 owner；保留已有 `web_attachments.json` schema 2 及
`web_attachment_cache` 物理名称，旧 Web 绝对路径不变。新增可选 `channel`、`retained_at`；
旧项按 Web 处理，基于原 30 天 expiry 推导提交时间。pending 飞书记录新增可选 `attachment_id,cwd`，
仍按 sender/chat/thread/cwd 消费，跨工作区失效。原 pending 绝对路径仍可消费，原 TTL 行为保留。
新文件不再写入 `_feishu_attachments`，不扫描或迁移历史工作目录。
飞书仍支持一般文件；Web 保留既有大小/数量、原生媒体与认证预览限制。
私有缓存里因崩溃遗留、超过 pending TTL 的无索引文件可清理，仅匹配 UUID 文件名且不跟随 symlink，
在途 pin 除外。损坏索引不授权扫描删除。保留索引是为了重启后安全定位、验证和清理文件。

终态与图片 store 在原 JSON schema 中增加可选单调递增 `pruned_before` UTC 截止时间，与明细删除原子提交。
旧文件缺失该字段表示尚未清理。截止时间防止已删除的历史明细被当作“从未投递”；更早或无法证明开始时间的
旧执行不自动重发。执行的 process-local monotonic 时刻须转换成 UTC 后比较；正在运行的长任务使清理截止时间
前移。截止时间只有一个标量，不生成无限 tombstone；提高保留期不会回退它。损坏凭据拒绝授权重发。
恢复投递 worker 尚未结束时，暂缓终态和图片明细清理。
这些凭据应随实例保留到 purge；手工删掉凭据将丢失去重证明。

浏览器 `focus-web.data-retention.v1` 只保存草稿活动时间和输入历史各项时间，不复制正文、不保存账号凭据。
旧的无时间数据从首次登记开始获得完整保留期。草稿在挂载与每分钟心跳续期，手动清理保护当前文档的挂载草稿；
长期休眠的其他文档按最后活动时间处理。历史写入重新读取存储并校验内容变更标记；时间戳写入失败会撤销旧的删除依据。诊断合并按到期规则过滤，避免旧内存快照复活过期项。
未取得当前服务器策略时不清理。浏览器存储失败可见，不影响发送正文。
服务端诊断拒绝重新同步已超过当前记录保留期的浏览器提交时间。

## 4. Wire 与验证

Wire v39：GET/POST `/api/settings/data-retention` 读取或部分更新两个周期；POST `/api/data/prune` 接受空对象。
均要求有效登录和文档凭据，POST 另需 CSRF；不消耗导航 intent。返回的策略是已提交值。
清理响应包含 `policy,results,errors,records,bytes_freed`，各 owner 的失败不伪装为空成功；字节数仅统计已释放的文件字节。
固定 DTO、端点与会话活动分类由 `bot/focus_web_wire_catalog.py` 定义。服务端与静态资源同版本部署。

回归入口：`tests/test_data_retention_config.py`、`tests/manage_cli/test_data.py`、`tests/test_data_retention.py`、`tests/test_web_gateway_data_retention.py`、
`tests/test_web_attachment_store.py`、`tests/focus_runtime/test_codex_handler_prompt_files.py`、
`web/test/data-retention.test.ts`、`web/test/data-retention-browser.test.ts`。
