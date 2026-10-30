"""Durable display-only submission evidence; never a prompt execution ledger.

See docs/contracts/focus-web-prompt-timing.zh-CN.md. Writes belong to the
Gateway's observation worker, outside RuntimeLoop. No prompt content is stored.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from typing import Any
from bot.data_retention_contract import DataPruneResult
from bot.stores.data_retention_store import DataRetentionStore


class WebPromptTimingStore:
    def __init__(self, data_dir: pathlib.Path) -> None:
        self.path = pathlib.Path(data_dir) / "web_prompt_timing.sqlite"
        self._lock = threading.RLock()
        self._retention = DataRetentionStore(data_dir)

    @contextmanager
    def _connection(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.25)) as db, db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError("Unsupported prompt timing schema")
                if version == 0:
                    db.execute("""CREATE TABLE IF NOT EXISTS submissions (
                        id TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL, turn_id TEXT NOT NULL DEFAULT '',
                        item_id TEXT NOT NULL DEFAULT '', submitted_at_ms INTEGER NOT NULL,
                        received_at_ms INTEGER, result TEXT NOT NULL DEFAULT 'unconfirmed',
                        reason_code TEXT NOT NULL DEFAULT '', epoch TEXT NOT NULL DEFAULT '',
                        observation_id TEXT NOT NULL DEFAULT '',
                        stages TEXT NOT NULL DEFAULT '[]', browser TEXT NOT NULL DEFAULT '{}',
                        updated_at_ms INTEGER NOT NULL)""")
                    db.execute("CREATE INDEX IF NOT EXISTS submission_item ON submissions(thread_id,turn_id,item_id)")
                    db.execute("CREATE INDEX IF NOT EXISTS submission_thread ON submissions(thread_id,submitted_at_ms)")
                    db.execute("PRAGMA user_version=1")
                    version = 1
                if version == 1:
                    db.execute("""ALTER TABLE submissions ADD COLUMN first_output TEXT NOT NULL
                        DEFAULT '{"status":"not_recorded","reason_code":""}'""")
                    db.execute("PRAGMA user_version=2")
                self.path.chmod(0o600)
                db.row_factory = sqlite3.Row
                yield db

    def receive(self, value: dict[str, Any]) -> bool:
        with self._connection() as db:
            # A browser-only row is not service evidence. Only this observed
            # request may establish the service identity, time and write token.
            cursor = db.execute("""INSERT INTO submissions
                (id,client_id,thread_id,submitted_at_ms,received_at_ms,epoch,observation_id,updated_at_ms,first_output)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                client_id=excluded.client_id, thread_id=excluded.thread_id,
                received_at_ms=excluded.received_at_ms, epoch=excluded.epoch,
                observation_id=excluded.observation_id, updated_at_ms=excluded.updated_at_ms,
                first_output=excluded.first_output
                WHERE submissions.received_at_ms IS NULL
                AND submissions.submitted_at_ms=excluded.submitted_at_ms
                AND (submissions.thread_id=excluded.thread_id OR submissions.thread_id='')""",
                (value['submission_id'], value['client_id'], value['thread_id'], value['submitted_at_ms'],
                 value['received_at_ms'], value['epoch'], value['observation_id'], value['received_at_ms'],
                 json.dumps(value['first_output'])))
            return cursor.rowcount == 1

    def update(self, value: dict[str, Any]) -> bool:
        with self._connection() as db:
            cursor = db.execute("""UPDATE submissions SET thread_id=?,
                turn_id=CASE WHEN ?!='' THEN ? ELSE turn_id END,
                result=CASE WHEN result='succeeded' THEN result ELSE ? END,
                reason_code=?, stages=?, updated_at_ms=?, first_output=?
                WHERE id=? AND observation_id=?""",
                (value['thread_id'], value['turn_id'], value['turn_id'], value['result'],
                 value['reason_code'], json.dumps(value['stages']), value['updated_at_ms'], json.dumps(value['first_output']),
                 value['submission_id'], value['observation_id']))
            return cursor.rowcount == 1

    def sync_browser(self, client_id: str, records: list[dict[str, Any]]) -> None:
        now = int(time.time() * 1000)
        cutoff = now - self._retention.load().records_days * 86_400_000
        with self._connection() as db:
            for record in records:
                if record['submitted_at_ms'] < cutoff:
                    continue
                db.execute("""INSERT INTO submissions
                    (id,client_id,thread_id,submitted_at_ms,browser,updated_at_ms)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET browser=excluded.browser
                    WHERE submissions.submitted_at_ms=excluded.submitted_at_ms
                    AND (excluded.thread_id='' OR submissions.thread_id=excluded.thread_id)
                    AND (json_extract(submissions.browser,'$.completed_at_ms') IS NULL
                         OR json_extract(excluded.browser,'$.completed_at_ms') IS NOT NULL)""",
                    (record['submission_id'], client_id, record['thread_id'], record['submitted_at_ms'],
                     json.dumps(record['browser']), now))

    def prune(self, before: float, *, protected_ids: tuple[str, ...] = ()) -> DataPruneResult:
        if not self.path.exists():
            return DataPruneResult()
        with self._lock:
            size = self.path.stat().st_size
            with self._connection() as db:
                candidates = db.execute("SELECT id FROM submissions WHERE updated_at_ms<?", (int(before * 1000),)).fetchall()
                ids = [(row['id'],) for row in candidates if row['id'] not in protected_ids]
                db.executemany("DELETE FROM submissions WHERE id=?", ids)
            if ids:
                with self._connection() as db:
                    db.execute("VACUUM")
            return DataPruneResult(len(ids), max(0, size - self.path.stat().st_size))

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result['submission_id'] = result.pop('id')
        result.pop('client_id')
        result.pop('observation_id')
        result['stages'] = json.loads(result['stages'])
        result['browser'] = json.loads(result['browser'])
        result['first_output'] = json.loads(result['first_output'])
        return result

    def detail(self, submission_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
            return self._decode(row) if row else None

    def recent(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM submissions WHERE thread_id=? ORDER BY submitted_at_ms DESC LIMIT 32",
                              (thread_id,)).fetchall()
            return [self._decode(row) for row in rows]

    def attach(self, thread_id: str, rows: list[dict[str, Any]]) -> None:
        users = [row for row in rows if row.get('role') == 'user']
        if not users:
            return
        with self._connection() as db:
            for row in users:
                client_message_id = row.get('clientUserMessageId', '')
                submission_id = client_message_id.removeprefix('focus-web:') if isinstance(client_message_id, str) else ''
                turn_id, item_id = row.get('rawTurnId', ''), row.get('itemId', '')
                if submission_id and turn_id and item_id:
                    db.execute("""UPDATE submissions SET turn_id=?,item_id=?,result='succeeded',updated_at_ms=?
                        WHERE id=? AND thread_id=? AND received_at_ms IS NOT NULL
                        AND (item_id='' OR (item_id=? AND turn_id=?))
                        AND (item_id='' OR result!='succeeded')""",
                        (turn_id, item_id, int(time.time() * 1000), submission_id, thread_id, item_id, turn_id))
                record = db.execute("""SELECT id,submitted_at_ms FROM submissions WHERE thread_id=?
                    AND received_at_ms IS NOT NULL AND (
                        (id=? AND (item_id='' OR (turn_id=? AND item_id=?)))
                        OR (turn_id=? AND item_id=? AND item_id!='')) LIMIT 1""",
                    (thread_id, submission_id, turn_id, item_id, turn_id, item_id)).fetchone()
                if record:
                    row['promptTiming'] = {'submissionId': record['id'], 'submittedAtMs': record['submitted_at_ms']}

    def delete_thread(self, thread_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM submissions WHERE thread_id=?", (thread_id,))
