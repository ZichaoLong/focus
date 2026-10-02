from unittest.mock import Mock

import pytest

from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from tests.codex_app_server_test_support import _FakeRpc


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
