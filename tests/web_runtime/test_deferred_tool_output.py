import json
from unittest.mock import patch

import pytest

from bot.adapters.base import ThreadSnapshot, ThreadSummary, ThreadTurnsPage
from bot.web_runtime.notification_projection import (
    WebNotificationProjectionReceipt,
    project_notification,
)
from bot.web_runtime.projection import (
    project_thread_inspection_tool,
    project_thread_snapshot,
    project_turns,
)
from bot.web_runtime.thread_read_model import WebThreadNotificationUpdate, WebThreadReadModel
from bot.web_runtime.thread_read_projection import (
    WebThreadHistoryProjection,
    WebThreadProjectionReceipt,
    project_older_turns,
)


def raw_turn(status="completed"):
    return {
        "id": "turn", "status": "inProgress", "items": [
            {"id": "cmd", "type": "commandExecution", "command": "echo evidence",
             "status": status, "aggregatedOutput": "saved evidence\n" * 5000},
            {"id": "edit", "type": "fileChange", "status": status, "changes": [
                {"path": "one.txt", "kind": {"type": "update"}, "diff": "@@ -1 +1 @@\n-old\n+new\n"},
                {"path": "two.txt", "kind": {"type": "add"}, "diff": "+second\n"},
            ]},
        ],
    }


def assert_deferred(turns):
    tools = [tool for turn in turns for tool in turn.get("tools", [])]
    assert len(tools) == 3
    assert [tool["inspectionLocator"]["change_index"] for tool in tools] == [None, 0, 1]
    for tool in tools:
        assert tool["outputDeferred"] is True
        assert tool["output"] == []
        assert not {"diff", "outputTruncated", "outputOmittedChars", "outputHeadLineCount"} & tool.keys()
    assert len(json.dumps(turns)) < 2500


@pytest.mark.parametrize("mode,ephemeral,deferred", [
    ("paginated", False, True), ("legacy", False, False),
    (None, False, False), ("paginated", True, False),
])
def test_snapshot_requires_known_persisted_history(mode, ephemeral, deferred):
    summary = ThreadSummary("thread", "/work", "Title", "", 0, 0, "cli", "idle",
                            history_mode=mode, ephemeral=ephemeral)
    result = project_thread_snapshot(ThreadSnapshot(summary, [raw_turn()]), owner={},
                                     pending_requests=[], coordinates={})
    if deferred:
        assert result["turns"] == []  # paginated open carries prompt summaries only
    else:
        assert result["turns"][0]["tools"][0]["output"]
        assert "outputDeferred" not in result["turns"][0]["tools"][0]


def test_deferral_avoids_output_and_diff_materialization_but_detail_reads_retain_content():
    turn = raw_turn()
    with patch("bot.web_runtime.projection.present_tool_output", side_effect=AssertionError), \
         patch("bot.web_runtime.projection._unified_diff_lines", side_effect=AssertionError):
        assert_deferred(project_turns([turn], defer_tool_output=True))
    command = project_thread_inspection_tool(turn["items"][0], "turn", None)
    edit = project_thread_inspection_tool(turn["items"][1], "turn", 1)
    assert command["output"]
    assert edit["output"] == ["+second", ""]
    assert edit["diff"]["lines"]
    assert "outputDeferred" not in command


@pytest.mark.parametrize("status", ["inProgress", "unknown"])
def test_nonterminal_outputs_are_never_deferred(status):
    tools = project_turns([raw_turn(status)], defer_tool_output=True)[0]["tools"]
    assert all(tool["output"] and "outputDeferred" not in tool for tool in tools)


def test_missing_source_identity_and_unsupported_tools_keep_inline_output():
    turn = raw_turn()
    turn.pop("id")
    assert all("outputDeferred" not in tool for tool in project_turns([turn], defer_tool_output=True)[0]["tools"])
    turn = raw_turn()
    turn["items"][0].pop("id")
    turn["items"].append({"id": "other", "type": "dynamicToolCall", "tool": "plugin", "status": "completed",
                          "contentItems": [{"type": "inputText", "text": "plugin output"}]})
    tools = project_turns([turn], defer_tool_output=True)[0]["tools"]
    assert tools[0]["output"] and "outputDeferred" not in tools[0]
    assert tools[-1]["output"] == ["plugin output"]


def test_history_pages_and_live_receipts_share_deferral_without_mutating_source():
    model = WebThreadReadModel()
    source = raw_turn()
    prepared = model.prepare_turn_replacement("thread", [source], history_mode="paginated")
    assert model.history_mode("thread") == ""
    model.install_prepared_turns(prepared)
    observation = model.capture_observation("thread")
    projection = WebThreadHistoryProjection(
        client_id="client", document=None, connection_generation=1, observation=observation,
        items_view="full", page=ThreadTurnsPage(turns=[raw_turn()]),
        receipt=WebThreadProjectionReceipt("epoch", 1), defer_tool_output=True,
    )
    urls = {"attachment_url_for_path": lambda path: path, "attachment_url_for_id": lambda key: key}
    assert_deferred(project_older_turns(projection, **urls)["turns"])
    receipt = WebNotificationProjectionReceipt(
        sequence=1, method="item/completed", thread_id="thread", runtime_epoch="epoch", observation=observation,
        update=WebThreadNotificationUpdate(method="item/completed", thread_id="thread", raw_turn=prepared.projection_turns[0]),
        defer_tool_output=model.history_mode("thread") == "paginated",
    )
    rows = project_notification(receipt, **urls)["item_turns"]
    assert len(rows) == 2
    assert all(row["contentDeferred"] and len(row["tools"]) == 1 for row in rows)
    assert all(row["tools"][0]["output"] == [] for row in rows)
    assert prepared.projection_turns[0]["items"][0]["aggregatedOutput"] == ""
    assert source["items"][0]["aggregatedOutput"]


@pytest.mark.parametrize("forget", ["forget_runtime", "forget_closed_thread", "forget_thread", "backend_disconnected"])
def test_lifecycle_clears_saved_history_observation(forget):
    model = WebThreadReadModel()
    model.install_prepared_turns(model.prepare_turn_replacement("thread", [], history_mode="paginated"))
    assert model.history_mode("thread") == "paginated"
    getattr(model, forget)(*(() if forget == "backend_disconnected" else ("thread",)))
    assert model.history_mode("thread") == ""
