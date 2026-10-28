# fcodex steer 空上下文字段兼容验证（2026-10-28）

本文记录一次 Focus 运行时兼容修复及候选 Codex 0.165.0 schema 比对。
行为规范见 [fcodex 共享 same-turn input 合同](../contracts/fcodex-operation-owner.zh-CN.md#共享-same-turn-input)。
没有修改上游代码、部署中的服务或真实会话数据。

## 缺陷与修复边界

原生 TUI 的 `turn/steer` 请求显式携带
`responsesapiClientMetadataPatch: null`。Focus 的已提交 schema 已包含该字段，
但 `strict_fcodex_steer_target` 的参数白名单遗漏了它，导致请求在转发前被拒绝，
proxy 返回 `-32002`。

固定上游证据为 Codex 0.164.0 commit
`fe3b29455488c2e189e43ad5526a107900c5e1b7` 的
[`TurnSteerParams`](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/app-server-protocol/src/protocol/v2/turn.rs)
及
[`AppServerSession::turn_steer`](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/tui/src/app_server_session.rs)。
本次另用实际部署版本 0.165.0 的生成 schema 确认：`turn/steer` 的归一化参数结构
及可达定义指纹与现有 0.164.0 基线一致。

修复只把此字段加入已审阅参数与实验上下文字段集合：缺省或 null 可通过；
非 null 值（含空 object）仍拒绝。请求原样转发，线程身份、连接准入和
`expectedTurnId` 边界不变。没有增加重试、自动改成 `turn/start`、队列或持久化记录。

## 回归证据

- 修改 production code 前，完整原生参数准入及 proxy 联合回归均失败；proxy
  回归得到与事故相同的 `-32002` 拒绝文本。
- 修改后，`fcodex-runtime` 固定验证锥的 284 个测试通过。
- schema 漂移守卫的 21 个单元测试通过。
- steer 测试使用完整原生参数，核对字段集合与已提交 schema 相同；未来更新
  schema 时，如果忘记同步该请求用例，测试会失败。
- proxy 联合回归使用真实 `OperationOwnerCoordinator` 准入与结算，确认原始请求和
  成功响应原样转发、连接不关闭、请求结算后不残留且 writer lease 不变。transport
  使用测试替身，没有向真实 Codex 会话发送 steer。
- 参数缺省/null、非空及空 object、错误身份、未 attach、跨前端与 stale turn
  边界由同一验证锥覆盖。
- Ruff、Python import cycle/dependency direction、source-context、文档与导航引用检查通过。

此验证证明 Focus 兼容补丁的范围，不声称改变上游 TUI 对其他 RPC 错误的退出行为。

## 0.165.0 schema 升级评估

现有基线记录的是 0.164.0，而部署二进制自报 `codex-cli 0.165.0`。
候选 schema 使用以下命令生成到临时目录：

```bash
codex app-server generate-json-schema --out "$schema_dir" --experimental
python scripts/check_codex_app_server_drift.py --schema-dir "$schema_dir"
```

本次候选 Linux x86_64 二进制 SHA-256：
`c06a67fd8ac76508dc78bd99ce20c9f317b8d568beda59485f3f4134df9962d5`。

整体漂移检查失败，首先报告新增 `thread/memory/read` 缺少显式分类。
另外直接比较生成的 inventory 与 fingerprint，得到：

| 范围 | 相对现有基线的变化 |
| --- | --- |
| ClientRequest inventory | 新增 `thread/memory/read`；没有移除 method |
| `thread/fork` 参数 | 新增 `attachToSource` |
| `thread/list` 参数 | 新增 `attachedToThreadId` |
| `thread/sample` 参数 | 新增 `threadSource` |
| 已追踪 response 定义 | 12 个 response root 的可达定义指纹变化 |
| 已追踪 notification 定义 | `error`、`thread/started`、`turn/completed`、`turn/started` 指纹变化 |
| ServerRequest / ServerNotification inventory、ThreadItem | inventory 不变；已追踪 ThreadItem 指纹不变 |
| `turn/steer` | 参数结构及可达定义指纹均不变 |

建议后续按 [schema 漂移合同](../contracts/codex-app-server-schema-drift.zh-CN.md)
审阅并更新到与实际部署一致的版本，尤其确认 attached fork、列表过滤和响应变化
是否影响 Focus 的 direct-root 与线程发现边界。新增接口可以显式决定不支持；
升级基线不等于自动开放全部新功能。

本次没有刷新基线，也不把候选版本整体漂移检查的失败计为已修复。
steer 修复不依赖该升级；仅修改基线版本号也不能修复运行时白名单遗漏。
