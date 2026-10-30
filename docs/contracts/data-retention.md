# Focus data cleanup

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/data-retention.zh-CN.md`.

## 1. Controls and scope

Focus Web settings exposes three controls: **Focus record retention**, **Attachment retention**, and
**Clean expired data now**. Each period independently offers 7 / 30 / 90 days, defaults to 30, persists per instance,
and takes effect without restart. Clean now applies the same expiry rules; it does not clear all data.
The sole configuration source is the instance's `codex.yaml`:

```yaml
records_retention_days: 30
attachments_retention_days: 30
```

Without Web, use the following commands. Each accepts one `--instance <name>` with normal focusctl selection:

```bash
focusctl data status
focusctl data retention --records-days 30 --attachments-days 30
focusctl data prune
```

`status` displays effective periods and the config path; `retention` accepts either period independently.
Both work while stopped. Web, CLI and manual YAML edits share this file; settings reads and automatic/manual sweeps
reload it without restart. `prune` requests the running Focus service through its authenticated local control plane,
independent of Web. A stopped/unreachable service returns an error; the CLI never deletes history directly.
The CLI cleans server data only; browsers clean their own local storage. Exit codes: 0 for success, 1 for partial owner
failure, 2 for invalid input/configuration, service errors or unknown outcomes. Unknown outcomes are not retried.

Web results distinguish server and current-browser item counts, including partial failures.
Server maintenance runs every 30 minutes, first running 30 minutes after startup; diagnostics also retain their startup sweep.
Browser maintenance runs after fetching current server policy, every 30 minutes, and on manual cleanup.
Other browsers clean their own storage when next opened. Opening settings refreshes policy. A shorter period takes effect
at the next sweep; extending it cannot recover deleted data.

These settings cover disposable Focus history with age-based retention, rather than replacing every data lifecycle.
Codex thread data remains managed through Codex archive/delete APIs. Configuration, bindings, group activation/context
boundaries, preferences, authentication, leases, live operations and uncertain-outcome recovery receipts keep their
existing lifecycles. Completed Feishu destination-loss proofs stay capped at 4096; pending proofs continue retrying.
System journal, user-generated workspace files and historical workspace attachments are outside the new attachment policy.

`focusctl purge` still uninstalls and removes validated machine-level Focus config/data roots, including the new cache.
It does not remove browser storage, Codex data or historical workspace attachments. `focusctl logs status` displays the
selected record period; `logs prune` uses it by default. Explicit `--keep-days` overrides only that diagnostic cleanup.

## 2. Previous and new rules

| Data | Previous rule | New rule and clock |
| --- | --- | --- |
| Focus diagnostic logs | Fixed 30 days plus capacity rotation | Record period from last file write; capacity and current-log protection unchanged |
| Group message logs | No age cleanup | Record period from message `created_at`; active groups and activation/boundaries protected |
| Terminal reply details | No age cleanup | Record period from `recorded_at` |
| Image delivery details | No age cleanup | Record period from `delivered_at`; generated source image remains |
| Server browser navigation profiles | No age cleanup | Record period from `updated_at`; live documents renewed |
| Browser input history | 100 entries per scope, no age limit | Per-entry save time plus record period; 100-entry cap remains |
| Browser drafts | Removed on send/clear | Record period from save/edit activity; mounted drafts protected |
| Server prompt diagnostics | Associated entries until explicit Web deletion, unassociated entries 90 days | Record period from latest diagnostic update for all entries; active traces protected; thread deletion still cleans immediately |
| Browser prompt diagnostics | 64 entries | Submission time plus record period; cap remains, in-flight submissions protected |
| Submitted Web attachments and media preview copies | 30 days, 512 MiB / 1024 files | Attachment period; capacity shared with new Feishu attachments may evict earlier |
| Newly consumed Feishu attachments | Kept in each cwd without age cleanup | Same private attachment cache and attachment period |
| Pending attachments | `attachment_ttl_seconds`, default 1800 seconds | Existing TTL, independent of both settings |

Retention grants deletion eligibility, not a precise deadline. Active workspaces defer submitted-file cleanup; in-flight
pins defer physical unlink. Capacity is checked during sweeps and avoids active workspaces and newly submitted files, so usage can temporarily exceed limits. Metadata retirement
precedes byte deletion. Group rows without valid timestamps remain; file times cannot substitute for message evidence.
One corrupt owner reports failure without blocking other owners.

## 3. Ownership, persistence and restart

`CodexConfig` owns the strict `records_retention_days,attachments_retention_days` schema. `DataRetentionStore` owns
reads/writes of these YAML fields; API/CLI `records_days,attachments_days` are projections. Missing fields use defaults;
invalid YAML/values neither overwrite settings nor authorize deletion. A cross-process `codex.yaml.lock` and private
atomic writes prevent lost partial Web/CLI updates. Other explicit values survive updates; YAML is reserialized and
comments/formatting are not preserved. There is no second policy file or long-lived in-memory copy. Removing a field
restores that field's default on the next read.

Legacy `data_retention.json` (schema 1) is migrated on first settings access: fill only fields not explicitly present
in YAML, atomically commit YAML, then delete the JSON. Interrupted migration is retryable. Both explicit YAML fields
form the commit checkpoint: stale or even corrupt JSON cannot override them and is retired. If fields still need
migration but JSON is corrupt/unknown-schema, migration and cleanup fail without modifying the source; basic conversation
startup remains available. Explicitly replacing both periods through the CLI needs no legacy inference, so it can commit
YAML and retire a corrupt old file. After migration JSON is no longer read or written. The first status/diagnostic policy read
may perform this migration.

`DataRetentionService` serializes service-side updates/sweeps and owns the periodic worker; existing stores remain data
owners. Web, CLI and automatic cleanup use this same service owner under an ingress receipt covering the whole sweep.
Control requests keep blocking file work outside RuntimeLoop. Shutdown/offline maintenance rejects new sweeps; shutdown
stops the worker before releasing service authority, and a failed join retains authority.

`AttachmentStore` owns shared files, retaining physical `web_attachments.json` schema 2 and `web_attachment_cache` names
so existing absolute Web paths stay valid. Optional `channel,retained_at` fields distinguish new records; old entries are
Web records and infer submission time from the original 30-day expiry. Pending Feishu records add optional
`attachment_id,cwd` while preserving sender/chat/thread/cwd consumption and workspace invalidation. Legacy pending
absolute paths remain consumable with their original TTL behavior. New files no longer enter `_feishu_attachments`;
historical workspaces are neither scanned nor migrated. Feishu still supports general files; Web retains its size/count,
native-media and authenticated preview rules. Unindexed crash leftovers in the private flat cache are eligible after
pending TTL, only with UUID filenames, without following symlinks, excluding live pins. Corrupt indexes cannot authorize
orphan scanning. The index preserves restart-safe file identity, access and deletion.

Terminal and image stores add an optional monotonic UTC `pruned_before` scalar to their existing JSON schemas,
atomically committed with deletion. Missing means no retirement yet. The watermark prevents removed history from
becoming evidence of no delivery: older executions, or executions without a proven start time, cannot automatically
resend. Process-local monotonic execution timestamps must be converted to UTC; long-running tasks move the deletion
cutoff earlier. A single scalar avoids unbounded tombstones; increasing retention never rolls it back. Corrupt proof
cannot authorize replay. Terminal and image detail pruning is deferred while recovery delivery workers remain active.
Keep these receipts until instance purge; manually deleting them loses dedup evidence.

Browser `focus-web.data-retention.v1` stores draft activity and per-entry history timestamps, without copied text or
authentication credentials. Undated legacy data gets a full period from first registration. Mounted drafts renew on
mount and each minute; manual cleanup protects this document's mounted drafts. Long-suspended documents use last activity.
History writes reload current storage and validate content change markers; failed timestamp writes invalidate stale expiry evidence. Timing merges filter expiry to prevent stale snapshots resurrecting removed entries.
No browser cleanup runs before current server policy is available. Storage failure is visible and does not block sending
text. Server diagnostics refuse browser submissions whose submission time exceeds the current record period.

## 4. Wire and verification

Wire v39 adds GET/POST `/api/settings/data-retention` for reads/partial updates and POST `/api/data/prune` with an empty
object. Valid login and document credentials are required; POST also requires CSRF. These routes do not consume navigation
intent. Returned settings are committed values. Cleanup returns `policy,results,errors,records,bytes_freed`; failures are
not empty successes and byte counts describe released file bytes. `bot/focus_web_wire_catalog.py` owns endpoints, DTOs and
session-activity classification. Service and static assets deploy together.

Regression entries: `tests/test_data_retention_config.py`, `tests/manage_cli/test_data.py`, `tests/test_data_retention.py`, `tests/test_web_gateway_data_retention.py`,
`tests/test_web_attachment_store.py`, `tests/focus_runtime/test_codex_handler_prompt_files.py`,
`web/test/data-retention.test.ts`, `web/test/data-retention-browser.test.ts`.
