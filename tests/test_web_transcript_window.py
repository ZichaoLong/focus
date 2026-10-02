"""Bounded item reads and full-source locators for very large current turns."""
from __future__ import annotations

import json

import pytest
from multidict import MultiDict

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.gateway_request_decoder import decode_transcript_query
from bot.web_runtime.transcript_budget import (
    PREVIEW_METADATA_KEY, TRANSCRIPT_ITEM_CHARS, bounded_transcript_item,
)
from bot.web_runtime.transcript_window import project_transcript_item
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
