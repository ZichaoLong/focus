"""No mobile cache authority escapes the selected document or its local store."""

import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aiohttp import ClientSession, CookieJar

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage
from bot.web_runtime.auth import WebAuthManager
from bot.codex_protocol.client import CodexRpcError
from bot.focus_runtime.web_gateway_composition import compose_web_gateway
from bot.service_runtime_lifecycle import ServiceRuntimeIngressDispatcher
from bot.web_runtime.gateway import WebGatewayConfig
from bot.web_runtime.mobile_records import reading_rows, record_states
from bot.web_runtime.transcript_window import project_transcript_item
from tests.test_service_runtime_lifecycle import _LifecycleFixture
from tests.test_web_transcript_window import inspection, read  # noqa: F401 -- shared admitted inspection fixture
from tests.web_runtime.gateway_harness import WebGatewayHarness
from tests.web_runtime.harness import WebRuntimeControllerHarness


def test_projection_keeps_prose_and_semantic_breaks_without_tool_payload(inspection):  # noqa: F811
    items = [
        {"id": "q", "type": "userMessage", "content": [{"type": "text", "text": "question"}]},
        {"id": "t", "type": "commandExecution", "command": "sensitive", "aggregatedOutput": "private", "status": "completed"},
        {"id": "empty", "type": "agentMessage", "text": "  "},
        {"id": "r", "type": "reasoning", "summary": ["secret reasoning"]},
        {"id": "m", "type": "agentMessage", "phase": "commentary", "text": "intermediate"},
        {"id": "a", "type": "agentMessage", "text": "final"},
    ]
    inspection.list_items.return_value = ThreadItemsPage(items=[ThreadItemEntry("one", item) for item in reversed(items)])
    result = read(inspection, view="mobile_records")
    assert [r["kind"] for r in result["rows"]] == ["user", "tool", "break", "assistant", "assistant"]
    assert result["oldest"] == ["one", "q"]
    assert result["older"] is None
    assert "private" not in json.dumps(result) and "sensitive" not in json.dumps(result)
    assert "secret reasoning" not in json.dumps(result)
    assert result["rows"][1] == {"kind": "tool", "turn": "one", "item": "t"}
    assert reading_rows(project_transcript_item("one", items[-1])) == [result["rows"][-1]]


class MobileTranscriptRouteTests(WebGatewayHarness):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        assets = root / "static"
        assets.mkdir()
        (assets / "index.html").write_text("<html></html>", encoding="utf-8")
        self.runtime = WebRuntimeControllerHarness()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.runtime.fake.history_mode = "paginated"
        self.lifecycle = _LifecycleFixture().lifecycle
        self.lifecycle.start()

        def call(callback, *args, **kwargs):
            return callback(*args, **kwargs)

        ingress = ServiceRuntimeIngressDispatcher(self.lifecycle, call, call)
        self.gateway = compose_web_gateway(
            config=WebGatewayConfig(static_dir=assets), data_dir=root,
            projection=self.runtime.projection, web_runtime=self.runtime.controller,
            ingress=lambda: ingress, runtime_call=call, backend_reset=Mock(),
            operator_status=Mock(), data_retention=Mock(),
        )
        self.endpoint = self.gateway.start()
        self.session = ClientSession(cookie_jar=CookieJar(unsafe=True))

    async def test_retry_with_reading_mark_through_production_ingress(self):
        await self._authenticate()
        document = await self._register_document(incarnation_id="reading-window")
        headers = self._client_headers(document)
        async with self.session.post(self.endpoint + "/api/threads/thread-1/open", headers=headers) as response:
            self.assertEqual(response.status, 200)
        page = ThreadItemsPage(items=[ThreadItemEntry("turn-1", {"id": "reply", "type": "agentMessage", "text": "Recovered"})])
        self.runtime.fake.list_thread_items = Mock(side_effect=[TimeoutError(), page, page, page])
        url = self.endpoint + "/api/threads/thread-1/transcript"
        marked = {**headers, "X-Focus-Reading-Window": "1"}
        async with self.session.get(url, headers=marked) as response:
            self.assertEqual(response.status, 504)
            self.assertNotIn("X-Focus-Reading-Mark", response.headers)
        async with self.session.get(url, headers=marked) as response:
            self.assertEqual(response.status, 200)
            mark = response.headers["X-Focus-Reading-Mark"]
            body = await response.json()
            self.assertEqual(body["turns"][0]["text"], "Recovered")
            self.assertNotIn("reading_mark", body)
        async with self.session.get(url, headers=headers) as response:
            self.assertNotIn("X-Focus-Reading-Mark", response.headers)
            self.assertEqual(await response.json(), body)
        async with self.session.get(self.endpoint + "/api/threads/thread-1/mobile-records", headers=headers) as response:
            self.assertEqual((await response.json())["mark"], mark)
        # A failed read or retry must not strand an ingress receipt that blocks maintenance.
        self.assertTrue(self.lifecycle.prepare_offline_maintenance(lambda: True))
        self.lifecycle.stop()


class MobileRouteTests(WebGatewayHarness):
    async def test_status_checks_exact_document_scope_and_bounded_batch(self):
        await self._authenticate()
        async with self.session.post(self.endpoint+"/api/client/register", json={"incarnation_id":"checker"},
                                     headers={"Origin":self.endpoint,"X-Focus-Mobile-Records":"1"}) as response:
            scope=response.headers["X-Focus-Mobile-Record-Scope"]
            document=await response.json()
        url=self.endpoint+"/api/mobile/record-status"
        calls=[]
        def read(ids):
            calls.append(ids)
            return ["missing"]*len(ids)
        self.gateway._ports.mobile_record_states=read
        for ids,proof,status in [(["valid"],"x",409),(["a","a"],scope,400),([],scope,400),
                                 (["ok"]*33,scope,400),(["valid"],scope,200)]:
            async with self.session.post(url,json={"scope":proof,"threads":ids},headers=self._client_headers(document)) as res:
                self.assertEqual(res.status,status)
                if status==200:
                    self.assertEqual(await res.json(),{"scope":scope,"states":["missing"]})
        self.assertEqual(calls,[["valid"]])

    async def test_mobile_scope_and_admitted_page(self):
        url = self.endpoint + "/api/threads/thread-1/mobile-records"
        async with self.session.get(url) as response:
            self.assertEqual(response.status, 401)
        await self._authenticate()
        async with self.session.post(self.endpoint+"/api/client/register", json={"incarnation_id":"reader"},
                                     headers={"Origin":self.endpoint,"X-Focus-Mobile-Records":"1"}) as response:
            proof = response.headers["X-Focus-Mobile-Record-Scope"]
            document = await response.json()
        self.assertRegex(proof, "^[a-f0-9]{64}$")
        self.assertNotIn(proof, document.values())
        self.gateway._ports.prepare_transcript_window = lambda client, thread, **kw: ("transcript", {"thread":thread, **kw})
        async with self.session.get(url+"?cursor=older", headers=self._client_headers(document)) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["scope"], proof)
            self.assertIn("no-store", response.headers["Cache-Control"])
        for query in ("?view=transcript", "?turn_id=x", "?cursor=x&cursor=y", "?full=true", "?full=false"):
            async with self.session.get(url+query,headers=self._client_headers(document)) as response:
                self.assertEqual(response.status, 400)
        async with self.session.get(url, headers={**self._client_headers(document),"X-Focus-Web-Document":"old"}) as response:
            self.assertEqual(response.status, 409)


def test_proxy_labels_do_not_unlock_another_session():
    manager = WebAuthManager(session_ttl_seconds=60)
    def issue():
        return manager.issue_external_session(external_origin="https://same.example",proxy_identity="shared")
    a, b = issue(), issue()
    assert a.mobile_read_scope != b.mobile_read_scope
    assert manager.renew_if_live(a.session_token).mobile_read_scope == a.mobile_read_scope
    assert manager.authenticate(a.mobile_read_scope) is None


@pytest.fixture
def store():
    path = Path(__file__).resolve().parents[1] / "mobile/harmony/entry/src/main/resources/rawfile/records-sql.json"
    ops = json.loads(path.read_text())
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    def call(op, **data):
        args = dict(site="entry-a|https://a", scope="f"*64, thread="thread", key="hash", title="title",
                    now="100", mark="epoch:generation:observation", head="fingerprint", run="run-a",
                    reading="", before="100", mode="all", fence="1", seq="0", body='[{"kind":"user","text":"hello"}]', edge="", oldest='["turn","first"]')
        args.update(data)
        def execute(name):
            rows = []
            for statement in ops[name]:
                if statement.startswith("@"):
                    execute(statement[1:])
                elif statement.startswith("!"):
                    if not db.execute(statement[1:],args).fetchone():
                        raise ValueError("fence")
                elif statement.startswith("?"):
                    rows = [dict(r) for r in db.execute(statement[1:],args)]
                else:
                    db.execute(statement,args)
            return rows
        with db:
            return execute(op)
    call("schema")
    yield call
    db.close()


def enroll(store, **kw):
    store("register",**kw)
    store("enable",enable=1,**kw)
    store("auth",**kw)


def clean_copy(store, row):
    return store("cleanselected",choices=","+row["choice"]+",",locked=row["locked"],fence=row["fence"])


def test_fenced_publication_and_cleanup(store):
    enroll(store)
    opts = {"fence":"2"}
    store("start",**opts)
    store("write",**opts)
    assert store("book")[0]["complete"] == 0
    assert store("checkpoint")[0]["oldest"] == '["turn","first"]'
    with pytest.raises(ValueError):
        store("write",**opts)
    store("finish",**opts)
    assert store("book")[0]["complete"] == 1
    store("start",run="refresh",**opts)
    assert store("book")[0]["run"] == "run-a"  # Old complete edition survives interrupted replacement.
    assert clean_copy(store,store("candidates")[0]) == [{"removed":1}]
    for op, args in [("finish",opts),("write",opts),("windowlive",opts),("start",{"fence":"3"})]:
        with pytest.raises(ValueError):
            store(op,run="refresh",**args)
    assert store("list") == store("candidates") == store("chunk") == []
    store("allow")
    store("start",run="deliberate",fence="3")
    store("write",run="deliberate",fence="3")
    assert store("book")[0]["run"] == "deliberate"


def test_exact_instance_scope_and_retention(store):
    for name in ("a","b"):
        args = dict(site=name,run=name,fence=2)
        enroll(store,site=name)
        store("start",**args)
        store("write",**args)
        store("finish",**args)
    store("lock",site="a")
    assert store("book",site="a") == [] and store("list",site="a") == []
    assert store("book",site="b")[0]["run"] == "b"
    store("auth",site="a")
    assert store("book",site="a")[0]["run"] == "a"
    store("auth",site="a",scope="d"*64)
    assert store("candidates",site="a") == []
    store("enable",site="b",enable=0)
    assert store("list",site="b")[0]["bytes"] > 0
    store("closed",site="b")
    assert store("candidates",site="b")[0]["closed"] == 1
    store("enable",site="b",enable=1)
    store("checkpoint",site="b",fence=store("status",site="b")[0]["fence"])
    assert store("candidates",site="b")[0]["closed"] == 0
    store("forget",site="b")
    assert store("status",site="b") == store("chunk",site="b",run="b") == []


def test_outer_identity_change_and_late_revocation(store):
    enroll(store)
    store("start", fence=2)
    store("write", fence=2)
    store("reauthorize")
    assert store("book") == store("capture") == []
    assert store("candidates")  # The old edition stays locked until authorization.
    store("auth")
    assert store("book") == store("candidates") == []
    assert store("capture")  # Preserve the opt-in with the same shared-proxy session.
    fence = store("status")[0]["fence"]
    store("start", fence=fence)
    store("write", fence=fence)
    with pytest.raises(ValueError):
        store("revoke", scope="d" * 64)
    assert store("book")
    store("revoke")
    assert store("book") == store("candidates") == store("capture") == []


def test_quota_and_removed_thread_do_not_restart_writes(store):
    enroll(store)
    store("start", fence=2)
    store("write", fence=2)
    with pytest.raises(ValueError):
        store("write", fence=2, seq=1, body="x" * (16 * 1024 * 1024))
    assert store("book")[0]["seq"] == 1
    assert clean_copy(store,store("candidates")[0]) == [{"removed":1}]
    store("enable", enable=0)
    store("enable", enable=1)
    assert store("capture") == []
    store("allow")
    assert store("capture")


def test_cleanup_rechecks_selected_copies_in_one_site_transaction(store):
    def save(site, thread, touched):
        data = dict(site=site, thread=thread, key=thread, title=thread, now=str(touched),
                    run=site+"-"+thread, fence=store("status",site=site)[0]["fence"])
        store("start",**data)
        store("write",**data)

    for site in ("a","b"):
        enroll(store,site=site)
    for thread in ("boundary","reread","closed","reopened","closed-reread","omitted","current"):
        save("a",thread,101 if thread in ("closed","reopened","closed-reread") else 100)
    for thread in ("closed","reopened","closed-reread"):
        store("closed",site="a",thread=thread)
    save("b","boundary",100)
    store("finish",site="a",thread="boundary",run="a-boundary",fence=2)
    store("start",site="a",thread="boundary",key="boundary",title="boundary",run="replacement",fence=2)
    store("write",site="a",thread="boundary",run="replacement",fence=2)
    old = dict(site="a", mode="old", before="100", reading="current")
    preview = {r["title"]:r for r in store("candidates",**old)}
    assert set(preview) == {"boundary","reread","closed","reopened","closed-reread","omitted"}
    assert preview["boundary"]["complete"] == 1
    visible = next(r for r in store("list",site="a") if r["title"]=="boundary")
    assert preview["boundary"]["bytes"] == 2*visible["bytes"]
    chosen = [r["choice"] for name,r in preview.items() if name != "omitted"]
    store("touch",site="a",thread="reread",now="110")
    store("touch",site="a",thread="closed-reread",now="110")
    store("checkpoint",site="a",thread="reopened",fence=2)
    save("a","arrived-after-preview",90)
    request = dict(**old, fence="2", locked="0", choices=","+",".join(chosen)+",")
    assert store("cleanselected",**request) == [{"removed":2}]
    assert store("cleanselected",**request) == [{"removed":0}]
    assert store("status",site="a")[0]["fence"] == 3
    assert {r["title"] for r in store("candidates",site="a")} == {
        "current","omitted","reread","reopened","closed-reread","arrived-after-preview"}
    assert store("candidates",site="b")[0]["title"] == "boundary"
    assert store("capture",site="a",key="boundary") == []


def test_cleanup_locked_preview_and_current_reader(store):
    enroll(store)
    store("start",fence=2,title="private title")
    preview = store("candidates")[0]
    assert preview["complete"] == -1  # No readable edition yet.
    request = dict(choices=","+preview["choice"]+",",fence="2",locked="0")
    assert store("cleanselected",reading="thread",**request) == [{"removed":0}]
    store("lock")
    assert store("cleanselected",**request) == [{"removed":0}]
    locked = store("candidates",reading="thread")[0]
    assert locked["locked"] == 1 and locked["reading"] == 1 and locked["title"] == ""
    assert store("candidates",mode="old",reading="thread") == []
    locked_request = dict(reading="thread",choices=","+locked["choice"]+",",fence=locked["fence"],locked="1")
    store("auth")
    assert store("status")[0]["fence"] == locked["fence"]
    assert store("cleanselected",**locked_request) == [{"removed":0}]
    store("lock")
    locked_request["fence"] = store("candidates",reading="thread")[0]["fence"]
    assert store("cleanselected",**locked_request) == [{"removed":1}]
    assert store("candidates") == []

def test_record_states_use_exact_read_and_preserve_ambiguous_outcomes():
    def read(thread, **kwargs):
        assert kwargs["include_turns"] is False and kwargs["expected_connection_generation"] == 7
        if thread == "unavailable":
            raise TimeoutError("metadata unavailable")
        if thread in {"gone", "unrelated"}:
            target = thread if thread == "gone" else "some-other-id"
            raise CodexRpcError("thread/read", {"message": f"thread not loaded: {target}"})
        paths = {"archived": r"C:\data\archived_sessions\old", "present": "/archive/archived_sessions/home/sessions/new"}
        return SimpleNamespace(summary=SimpleNamespace(thread_id=thread, ephemeral=False, path=paths.get(thread)))
    ids=["gone","unrelated","unavailable","archived","present","no-path"]
    assert record_states(ids, read, lambda:7) == ["missing","unknown","unknown","archived","present","unknown"]
    generations=iter([7,8])
    assert record_states(ids, read, generations.__next__) == ["unknown"]*len(ids)


def test_cleanup_revalidates_lifecycle_and_supports_legacy_closed_rows(store):
    enroll(store)
    store("start",fence=2)
    store("closed")
    assert store("candidates")[0]["closed"]==1
    store("lifecycle",reason="closed")
    assert store("candidates")[0]["closed"]==2
    store("lifecycle",reason="archived")
    archived=store("candidates")[0]
    assert archived["closed"]==3
    store("lifecycle",reason="closed")
    assert store("candidates")[0]["closed"]==3
    store("lifecycle",reason="unarchived")
    assert clean_copy(store,archived)==[{"removed":0}]
    store("lifecycle",scope="wrong",reason="deleted")
    assert store("candidates")[0]["closed"]==0
    store("lifecycle",reason="deleted")
    assert store("candidates")[0]["closed"]==4
    store("checklock",scope="wrong",fence=2)
    assert store("candidates")[0]["thread"]=="thread"
    store("checklock",fence=2)
    assert store("candidates")[0]["thread"]==store("status")[0]["scope"]==""
