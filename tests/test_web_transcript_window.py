"""Bounded item reads and full-source locators for very large current turns."""
from __future__ import annotations

import json

import pytest
from multidict import MultiDict

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage
from bot.codex_protocol.connection import CodexRpcError
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.gateway_request_decoder import decode_transcript_query
from bot.web_runtime.transcript_budget import (
    PREVIEW_METADATA_KEY, TRANSCRIPT_ITEM_CHARS, bounded_transcript_item,
)
from bot.web_runtime.transcript_window import project_transcript_item
from bot.web_runtime.transcript_source import encode_transcript_source
from tests import test_web_thread_inspection as support


@pytest.fixture
def inspection():
    case = support.WebThreadInspectionServiceTests(methodName="runTest")
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def entries(count, *, text="content"):
    return [ThreadItemEntry(turn_id="turn-1", item={
        "id": f"item-{i}", "type": "agentMessage", "text": text,
    }) for i in range(count)]


def read(case, **query):
    prepared = case.service.prepare_transcript_window("tab-1", "thread-1", **query)
    effect = case._execute(case.service, prepared)
    return case.service.settle_inspection(prepared, effect)


def test_page_is_bounded_and_chronological_with_opaque_direction_cursors(inspection):
    inspection.list_items.return_value = ThreadItemsPage(
        items=list(reversed(entries(40, text="中文😀" * 100_000))),
        next_cursor="older", backwards_cursor="newer",
    )
    result = read(inspection)
    assert result["turns"][0]["itemId"] == "item-0"
    assert result["turns"][-1]["itemId"] == "item-39"
    assert all(turn["contentDeferred"] for turn in result["turns"])
    assert len(json.dumps(result).encode()) < 2 * 1024 * 1024
    assert result["older_cursor"] == "older"
    assert result["newer_cursor"] == "newer"
    assert inspection.list_items.call_args.kwargs["limit"] == 40
    assert inspection.read_thread.call_args.args == ("thread-1", False)


def test_full_content_uses_two_indexed_reads_and_is_not_a_preview(inspection):
    text = "**完整**\n" * 30_000
    inspection.list_items.side_effect = [
        ThreadItemsPage(items=entries(1)),
        ThreadItemsPage(items=[ThreadItemEntry(turn_id="turn-1", item={
            "id": "target", "type": "agentMessage", "text": text,
        })]),
    ]
    result = read(inspection, turn_id="turn-1", item_id="target", full=True)
    assert result["full_text"] == text
    assert result["turns"] == []
    calls = inspection.list_items.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["anchor_item_id"] == "target"
    assert calls[0].kwargs["sort_direction"] == "desc"
    assert calls[1].kwargs["anchor_item_id"] == "item-0"
    assert all(call.kwargs["limit"] == 1 for call in calls)


def test_first_item_and_missing_target_do_not_scan_the_turn(inspection):
    inspection.list_items.side_effect = [ThreadItemsPage(), ThreadItemsPage(items=entries(1))]
    result = read(inspection, turn_id="turn-1", item_id="item-0", full=True)
    assert result["full_text"] == "content"
    assert inspection.list_items.call_args.kwargs["anchor_item_id"] is None
    inspection.list_items.side_effect = [ThreadItemsPage(), ThreadItemsPage(items=entries(1))]
    with pytest.raises(WebRuntimeError, match="no longer available"):
        read(inspection, turn_id="turn-1", item_id="different", full=True)


def test_mismatched_predecessor_fails_before_reading_a_different_turn(inspection):
    inspection.list_items.return_value = ThreadItemsPage(items=[ThreadItemEntry(
        turn_id="another-turn", item={"id": "predecessor"},
    )])
    with pytest.raises(WebRuntimeError) as failure:
        read(inspection, turn_id="turn-1", item_id="target", full=True)
    assert failure.value.code == "transcript_protocol_error"
    assert inspection.list_items.call_count == 1


def test_other_thread_revisions_do_not_starve_transcript_but_same_thread_is_fenced(inspection):
    prepared = inspection.service.prepare_transcript_window("tab-1", "thread-1")
    effect = inspection._execute(inspection.service, prepared)
    inspection.coordinates.return_value = {"runtime_epoch": "epoch-1", "revision": 99}
    assert inspection.service.settle_inspection(prepared, effect)["revision"] == 7
    inspection.read_model.observe_notification("thread-1")
    with pytest.raises(WebRuntimeError) as error:
        inspection.service.settle_inspection(prepared, effect)
    assert error.value.code == "stale_thread_read"


def test_transcript_rejects_replaced_document_backend_and_legacy(inspection):
    prepared = inspection.service.prepare_transcript_window("tab-1", "thread-1")
    effect = inspection._execute(inspection.service, prepared)
    inspection.documents.materialize_thread("tab-1", "thread-2")
    with pytest.raises(WebRuntimeError):
        inspection.service.settle_inspection(prepared, effect)
    inspection.documents.materialize_thread("tab-1", "thread-1")
    inspection.read_thread.return_value = support._snapshot(history_mode="legacy")
    with pytest.raises(WebRuntimeError):
        read(inspection)


@pytest.mark.parametrize("query", [
    {"full": "yes"}, {"direction": "up"}, {"unknown": "x"}, {"cursor": "x" * 4097},
])
def test_closed_query_rejects_ambiguous_inputs(query):
    with pytest.raises(WebRuntimeError):
        decode_transcript_query(MultiDict(query))


def test_budget_preserves_source_and_identity_and_bounds_nested_tool_projection():
    source = {"text": "x" * 1_000_000, "id": "stable", "type": "agentMessage"}
    bounded = bounded_transcript_item(source)
    assert len(bounded["text"]) == TRANSCRIPT_ITEM_CHARS
    nested = bounded_transcript_item({"id": "tool", "type": "dynamicToolCall",
        "arguments": {"id": "x" * 1_000_000, "k" * 1_000_000: "value"}})
    assert len(nested["arguments"]["id"]) <= TRANSCRIPT_ITEM_CHARS
    assert all(len(key) <= 256 for key in nested["arguments"])
    assert bounded["id"] == "stable"
    assert bounded[PREVIEW_METADATA_KEY].truncated
    assert len(source["text"]) == 1_000_000
    assert bounded_transcript_item(bounded)[PREVIEW_METADATA_KEY].truncated
    tool = support._file_change(changes=[{
        "path": "a" * 1000, "kind": {"type": "add"}, "diff": "+x" * 1000,
    } for _ in range(5000)])
    projected = project_transcript_item("turn-1", tool)
    assert len(json.dumps(projected).encode()) < 64 * 1024
    assert all(turn["contentDeferred"] for turn in projected)


def test_single_live_user_item_does_not_invent_an_empty_assistant_row():
    rows = project_transcript_item("turn-1", {
        "id": "prompt", "type": "userMessage", "content": [{"type": "text", "text": "steer"}],
    }, status="inProgress")
    assert [turn["role"] for turn in rows] == ["user"]


def test_deferred_command_output_keeps_semantic_card_and_detail_locator():
    item = {"id": "command", "type": "commandExecution", "status": "completed",
            "aggregatedOutput": "large output\n" * 100_000, "command": "pytest", "cwd": "/work"}
    rows = project_transcript_item("turn-1", bounded_transcript_item(item))
    assert "contentDeferred" not in rows[0]
    tool = rows[0]["tools"][0]
    assert tool["arg"] == "pytest" and tool["outputDeferred"]
    assert tool["inspectionLocator"]["item_id"] == "command"
    assert tool["output"] == []
    assert len(item["aggregatedOutput"]) > 1_000_000


def test_repeated_command_action_does_not_double_charge_the_card_budget():
    command = "python script.py " + "x" * 10_000
    action_command = "bash -lc '" + command + "'"
    item = {"id": "command", "type": "commandExecution", "status": "completed",
            "command": command, "commandActions": [{"type": "unknown", "command": action_command}],
            "aggregatedOutput": "done"}
    row = project_transcript_item("turn-1", item)[0]
    assert "contentDeferred" not in row
    assert row["tools"][0]["arg"] == command
    assert row["tools"][0]["inspectionLocator"]["item_id"] == "command"
    assert row["tools"][0]["commandExecution"]["commandActions"] == []
    assert item["commandActions"][0]["command"] == action_command
    full = project_transcript_item("turn-1", item, full=True)[0]
    assert full["tools"][0]["commandExecution"]["commandActions"][0]["command"] == action_command


def test_deferred_file_diffs_do_not_hide_later_paths_or_card_identity():
    item = support._file_change(changes=[{"path": path, "kind": {"type": "add"}, "diff": "+large\n" * 100_000}
                                        for path in ("one.py", "two.py")])
    row = project_transcript_item("turn-1", item)[0]
    assert "contentDeferred" not in row
    assert [tool["inspectionLocator"]["change_index"] for tool in row["tools"]] == [0, 1]
    assert all(tool["outputDeferred"] for tool in row["tools"])


def test_normal_chinese_reply_preserves_markdown_instead_of_size_fallback():
    text = "**正常回复**\n" + "内容" * 3000
    row = project_transcript_item("turn-1", {"id": "reply", "type": "agentMessage", "text": text})[0]
    assert row["text"] == text
    assert "contentDeferred" not in row
    assert row["blocks"][0]["text"] == text


def test_source_reread_uses_only_original_string_cursor_scope_and_exact_item(inspection):
    page = ThreadItemsPage(items=list(reversed(entries(40))), backwards_cursor="original-opaque", next_cursor="older")
    inspection.list_items.return_value = page
    preview = read(inspection)
    source = preview["turns"][5]["sourceCursor"]
    inspection.list_items.reset_mock()
    result = read(inspection, turn_id="turn-1", item_id="item-5", full=True, source_cursor=source)
    assert result["full_text"] == "content"
    inspection.list_items.assert_called_once()
    kwargs = inspection.list_items.call_args.kwargs
    assert kwargs["cursor"] == "original-opaque" and kwargs["turn_id"] is None
    assert kwargs["limit"] == 40 and kwargs["sort_direction"] == "desc"
    assert "anchor_item_id" not in kwargs
    with pytest.raises(WebRuntimeError, match="no longer available"):
        read(inspection, turn_id="wrong-turn", item_id="item-5", full=True, source_cursor=source)


def test_string_only_upstream_returns_cancellable_target_scan_pages(inspection):
    rejection = CodexRpcError("thread/items/list", {"code": -32600,
        "message": "Invalid request: invalid type: map, expected a string"})
    inspection.list_items.side_effect = [rejection, ThreadItemsPage(items=entries(40), next_cursor="continue")]
    page = read(inspection, turn_id="turn-1", item_id="item-99", full=True)
    assert page["target_pending"] and page["newer_cursor"] == "continue"
    assert page["turns"] == [] and page["full_text"] is None
    inspection.list_items.side_effect = None
    inspection.list_items.return_value = ThreadItemsPage(items=[ThreadItemEntry(turn_id="turn-1", item={
        "id": "item-99", "type": "agentMessage", "text": "exact target",
    })])
    result = read(inspection, turn_id="turn-1", item_id="item-99", cursor="continue", full=True)
    assert result["full_text"] == "exact target" and not result["target_pending"]
    assert inspection.list_items.call_args.kwargs["cursor"] == "continue"
    assert "anchor_item_id" not in inspection.list_items.call_args.kwargs


def test_string_cursor_target_keeps_surrounding_page_for_gapless_navigation(inspection):
    inspection.list_items.return_value = ThreadItemsPage(items=entries(40), next_cursor="after", backwards_cursor="before")
    result = read(inspection, turn_id="turn-1", item_id="item-20", cursor="scan-here")
    assert [row["itemId"] for row in result["turns"]] == [f"item-{n}" for n in range(40)]
    assert result["older_cursor"] == "before" and result["newer_cursor"] == "after"
    assert inspection.list_items.call_args.kwargs["turn_id"] is None


def test_prompt_anchor_reopens_a_thread_wide_page_and_crosses_the_turn_boundary(inspection):
    target = entries(1)[0]
    following = ThreadItemEntry(turn_id="turn-2", item={
        "id": "next-prompt", "type": "userMessage", "content": [{"type": "text", "text": "下一轮"}],
    })
    inspection.list_items.side_effect = [ThreadItemsPage(),
        ThreadItemsPage(items=[target], backwards_cursor="target-inclusive"),
        ThreadItemsPage(items=[target, following], backwards_cursor="global-before", next_cursor="global-after")]
    result = read(inspection, turn_id="turn-1", item_id="item-0")
    assert result["turn_id"] == "turn-1"  # Echo the locator identity, not a browsing filter.
    assert [row["rawTurnId"] for row in result["turns"]] == ["turn-1", "turn-2"]
    assert result["older_cursor"] == "global-before" and result["newer_cursor"] == "global-after"
    calls = inspection.list_items.call_args_list
    assert len(calls) == 3
    assert calls[-1].kwargs["turn_id"] is None
    assert calls[-1].kwargs["cursor"] == "target-inclusive"
    assert calls[-1].kwargs["limit"] == 40


def test_navigation_anchor_rejects_a_missing_inclusive_cursor(inspection):
    inspection.list_items.side_effect = [ThreadItemsPage(), ThreadItemsPage(items=entries(1))]
    with pytest.raises(WebRuntimeError, match="anchor cursor"):
        read(inspection, turn_id="turn-1", item_id="item-0")
    assert inspection.list_items.call_count == 2


def test_old_server_navigation_scans_globally_and_can_continue_across_turns(inspection):
    rejection = CodexRpcError("thread/items/list", {"code": -32600,
        "message": "Invalid request: invalid type: map, expected a string"})
    inspection.list_items.side_effect = [rejection, ThreadItemsPage(items=entries(40), next_cursor="global-next")]
    result = read(inspection, turn_id="turn-2", item_id="target")
    assert result["target_pending"] and result["newer_cursor"] == "global-next"
    assert inspection.list_items.call_args.kwargs["turn_id"] is None


def test_prompt_directory_finds_all_steers_and_never_returns_tool_bodies(inspection):
    def user(n):
        return ThreadItemEntry(turn_id="turn-1", item={"id": f"user-{n}", "type": "userMessage",
            "content": [{"type": "text", "text": f"追加{n}" + "内容" * 10_000}]})
    inspection.list_items.side_effect = [ThreadItemsPage(items=entries(100), next_cursor="skip-tools"),
        ThreadItemsPage(items=[user(2), user(1)], next_cursor="older")]
    result = read(inspection, view="prompts")
    assert [row["itemId"] for row in result["turns"]] == ["user-1", "user-2"]
    assert all(row["role"] == "user" and len(row["text"]) <= 161 for row in result["turns"])
    assert result["older_cursor"] == "older"
    assert inspection.list_items.call_count == 2
    assert inspection.list_items.call_args.kwargs["limit"] == 100
    assert inspection.list_items.call_args.kwargs["cursor"] == "skip-tools"


def test_empty_prompt_scan_returns_progress_after_four_pages(inspection):
    inspection.list_items.side_effect = [ThreadItemsPage(items=entries(100), next_cursor=f"next-{n}") for n in range(4)]
    result = read(inspection, view="prompts")
    assert result["turns"] == [] and result["older_cursor"] == "next-3"
    assert inspection.list_items.call_count == 4


@pytest.mark.parametrize("query", [
    {"view": "prompts", "item_id": "x", "turn_id": "turn-1"},
    {"view": "prompts", "direction": "asc"},
    {"source_cursor": "{}", "full": True, "item_id": "x", "turn_id": "turn-1"},
    {"source_cursor": encode_transcript_source("opaque", None, "desc", 40)},
])
def test_invalid_query_combinations_fail_before_upstream_io(inspection, query):
    with pytest.raises(WebRuntimeError):
        read(inspection, **query)
    inspection.list_items.assert_not_called()
