from unittest.mock import Mock

import pytest

from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from bot.adapters.codex_thread_inspection import thread_items_page_from_result
from bot.codex_protocol.client import CodexRpcProtocolError
from tests.codex_app_server_test_support import _FakeRpc


@pytest.mark.parametrize("fields, expected", [
    ({}, (None, None)),
    ({"startedAtMs": None, "completedAtMs": None}, (None, None)),
    ({"startedAtMs": 1_790_999_123_456, "completedAtMs": 1_790_999_124_789}, (1_790_999_123_456, 1_790_999_124_789)),
])
def test_item_page_preserves_optional_source_timestamps(fields, expected):
    entry = {"turnId": "turn-1", "item": {"type": "agentMessage", "id": "reply"}, **fields}
    result = thread_items_page_from_result({"data": [entry], "nextCursor": None, "backwardsCursor": None})
    assert (result.items[0].started_at_ms, result.items[0].completed_at_ms) == expected


@pytest.mark.parametrize("bad", [True, "123", 1.5, -1, float("nan"), 8_640_000_000_000_001])
@pytest.mark.parametrize("field", ["startedAtMs", "completedAtMs"])
def test_item_page_rejects_invalid_source_timestamps(field, bad):
    with pytest.raises(CodexRpcProtocolError):
        thread_items_page_from_result({"data": [{"turnId": "turn-1",
            "item": {"type": "agentMessage", "id": "reply"}, field: bad}],
            "nextCursor": None, "backwardsCursor": None})


def test_resume_can_request_summaries_without_changing_other_resume_consumers():
    adapter = CodexAppServerAdapter(CodexAppServerConfig())
    rpc = _FakeRpc()
    adapter._rpc = rpc
    adapter.resume_thread_page("thread-1", limit=10, items_view="summary")
    assert rpc.calls[0][1]["initialTurnsPage"]["itemsView"] == "summary"
    assert rpc.calls[0][1]["excludeTurns"] is True


def test_exact_item_anchor_is_forwarded_without_offset_or_legacy_scan():
    adapter = CodexAppServerAdapter(CodexAppServerConfig())
    adapter._rpc_request = Mock(return_value={"data": [], "nextCursor": None, "backwardsCursor": None})
    adapter.list_thread_items("thread-1", turn_id="turn-1", anchor_item_id="item-100000", limit=1, sort_direction="desc")
    assert adapter._rpc_request.call_args.args == ("thread/items/list", {
        "threadId": "thread-1", "turnId": "turn-1", "cursor": {"type": "item", "itemId": "item-100000"},
        "limit": 1, "sortDirection": "desc",
    })
    with pytest.raises(ValueError):
        adapter.list_thread_items("thread-1", anchor_item_id="item-1")
    with pytest.raises(ValueError):
        adapter.list_thread_items("thread-1", turn_id="turn-1", cursor="opaque", anchor_item_id="item-1")
