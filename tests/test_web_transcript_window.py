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
    TOOL_SUMMARY_CHARS, bounded_transcript_item,
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


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_page_is_bounded_and_chronological_with_opaque_direction_cursors(inspection, direction):
    text = "中文😀" * 10_000
    def page(_thread, **kwargs):
        count = kwargs["limit"]
        items = entries(40, text=text)
        if direction == "desc":
            items.reverse()
        return ThreadItemsPage(items=items[:count],
            next_cursor=f"next-{count}", backwards_cursor="backwards")
    inspection.list_items.side_effect = page
    result = read(inspection, direction=direction, cursor="original-edge")
    assert result["turns"][0]["itemId"] == ("item-30" if direction == "desc" else "item-0")
    assert result["turns"][-1]["itemId"] == ("item-39" if direction == "desc" else "item-9")
    assert all(turn["text"] == text and "contentDeferred" not in turn for turn in result["turns"])
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 2 * 1024 * 1024
    assert result["older_cursor"] == ("next-10" if direction == "desc" else "backwards")
    assert result["newer_cursor"] == ("backwards" if direction == "desc" else "next-10")
    assert [call.kwargs["limit"] for call in inspection.list_items.call_args_list] == [40, 20, 10]
    assert all(call.kwargs["cursor"] == "original-edge" for call in inspection.list_items.call_args_list)
    assert inspection.read_thread.call_args.args == ("thread-1", False)


def test_complete_long_reply_preserves_source_and_precise_times(inspection):
    inspection.list_items.return_value = ThreadItemsPage(items=[
        ThreadItemEntry("turn-1", {"type": "agentMessage", "id": "long", "text": "中文" * 30_000},
            started_at_ms=123_000, completed_at_ms=127_500),
        ThreadItemEntry("turn-1", {"type": "agentMessage", "id": "old", "text": "old"}),
    ])
    rows = {row["itemId"]: row for row in read(inspection)["turns"]}
    assert rows["long"]["text"] == "中文" * 30_000
    assert "contentDeferred" not in rows["long"]
    assert rows["long"]["reply"] == {"state": "complete", "startedAtMs": 123_000, "completedAtMs": 127_500}
    assert rows["old"]["reply"] == {"state": "unknown"}
    assert rows["old"]["blocks"][0]["reply"] == {"state": "unknown"}
    forged = project_transcript_item("turn-1", {"type": "agentMessage", "id": "fake", "text": "text",
        "_focus_reply_metadata": {"state": "complete", "completed_at_ms": 999}})
    assert forged[0]["reply"] == {"state": "unknown"}
    assert "reply" not in project_transcript_item("turn-1", {"type": "reasoning", "id": "r", "summary": ["thinking"]})[0]


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


def test_first_click_specialized_tool_detail_uses_exact_item_reads(inspection):
    tool = support._command("target")
    tool["aggregatedOutput"] = "complete output\n" * 8000 + "last line"
    inspection.list_items.side_effect = [
        ThreadItemsPage(items=entries(1)),
        ThreadItemsPage(items=[ThreadItemEntry("turn-1", tool)], next_cursor="unrelated"),
    ]
    result = inspection._read_tool_detail("tab-1", "thread-1", "turn-1", "target", view="full")
    assert result["status"] == "found" and result["next_cursor"] is None
    assert result["detail"]["source"]["aggregatedOutput"] == tool["aggregatedOutput"]
    first, second = inspection.list_items.call_args_list
    assert first.kwargs["anchor_item_id"] == "target" and first.kwargs["sort_direction"] == "desc"
    assert second.kwargs["anchor_item_id"] == "item-0" and second.kwargs["sort_direction"] == "asc"
    assert first.kwargs["limit"] == second.kwargs["limit"] == 1


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
    assert bounded["text"] == source["text"]
    nested = bounded_transcript_item({"id": "tool", "type": "dynamicToolCall",
        "arguments": {"id": "x" * 1_000_000, "k" * 1_000_000: "value"}})
    assert len(nested["arguments"]["id"]) <= TOOL_SUMMARY_CHARS
    assert all(len(key) <= 256 for key in nested["arguments"])
    assert bounded["id"] == "stable"
    assert len(source["text"]) == 1_000_000
    assert bounded_transcript_item(bounded) == bounded
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
    assert rows[0]["contentDeferred"]
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
    assert row["contentDeferred"]
    assert len(row["tools"][0]["arg"]) <= 512
    assert row["tools"][0]["inspectionLocator"]["item_id"] == "command"
    assert "commandExecution" not in row["tools"][0]
    assert item["commandActions"][0]["command"] == action_command
    full = project_transcript_item("turn-1", item, full=True)[0]
    assert full["tools"][0]["commandExecution"]["commandActions"][0]["command"] == action_command


def test_deferred_file_diffs_do_not_hide_later_paths_or_card_identity():
    item = support._file_change(changes=[{"path": path, "kind": {"type": "add"}, "diff": "+large\n" * 100_000}
                                        for path in ("one.py", "two.py")])
    row = project_transcript_item("turn-1", item)[0]
    assert row["contentDeferred"]
    assert len(row["tools"]) == 1
    assert json.loads(row["tools"][0]["arg"])["file_count"] == 2
    assert "inspectionLocator" not in row["tools"][0]


@pytest.mark.parametrize("item_type, name", [
    ("mcpToolCall", "MCP · research/search"), ("dynamicToolCall", "search"),
])
@pytest.mark.parametrize("prebounded", [False, True])
def test_clipped_tool_keeps_invocation_identity_before_output_and_arguments(item_type, name, prebounded):
    # Both output and deeply nested arguments can exhaust the source budget
    # before a later tool/server field in the upstream object.
    item = {"result": {"content": [{"type": "text", "text": "output" * 100_000}]},
            "arguments": {"query": "needle", "context": ["x" for _ in range(2000)]},
            "id": "search-1", "type": item_type, "status": "completed", "success": True,
            "server": "research", "tool": "search"}
    source = bounded_transcript_item(item) if prebounded else item
    row = project_transcript_item("turn-1", source)[0]
    assert row["contentDeferred"] and row["text"] == ""
    assert len(row["tools"]) == 1
    tool = row["tools"][0]
    assert tool["name"] == name and tool["status"] == "ok"
    assert '"query": "needle"' in tool["arg"]
    assert tool["output"] == [] and "inspectionLocator" not in tool
    assert row["blocks"] == [{"kind": "tool", "tool": tool}]
    assert len(json.dumps(row).encode()) < 4096
    assert len(item["result"]["content"][0]["text"]) == 600_000


@pytest.mark.parametrize("item, kind, index", [
    ({"id": "command", "type": "commandExecution", "status": "completed",
      "command": "python " + "script" * 10_000, "aggregatedOutput": "finished"}, "commandExecution", None),
    (support._file_change(changes=[{"path": "路径" * 6000, "kind": {"type": "add"}, "diff": "+x"}]), "fileChange", 0),
])
def test_clipped_command_and_single_file_keep_exact_specialized_reader(item, kind, index):
    row = project_transcript_item("turn-1", bounded_transcript_item(item))[0]
    assert row["contentDeferred"]
    tool = row["tools"][0]
    assert tool["output"] == [] and tool["outputDeferred"]
    assert tool["inspectionLocator"] == {
        "turn_id": "turn-1", "item_id": item["id"], "kind": kind, "change_index": index,
    }
    assert len(json.dumps(row).encode()) < 8192


def test_clipped_multifile_card_reads_the_entire_source_record(inspection):
    item = support._file_change(changes=[{
        "path": f"file-{i}-" + "x" * 1000, "kind": {"type": "add"}, "diff": f"+line {i}\n" * 100,
    } for i in range(100)])
    # Live cache rebounding must retain the original count, not the number of
    # paths that fit. No native locator may narrow the group to its first file.
    live = project_transcript_item("turn-1", bounded_transcript_item(item))[0]
    header = live["tools"][0]
    assert header["name"] == "File change"
    assert json.loads(header["arg"])["file_count"] == 100
    assert "inspectionLocator" not in header and "outputDeferred" not in header
    inspection.list_items.return_value = ThreadItemsPage(items=[ThreadItemEntry(
        turn_id="turn-1", item=item,
    )], backwards_cursor="original-page")
    preview = read(inspection)["turns"][0]
    assert preview["tools"] == live["tools"]
    detail = read(inspection, turn_id="turn-1", item_id=item["id"], full=True,
                  source_cursor=preview["sourceCursor"])
    assert json.loads(detail["full_text"]) == item


def test_running_tool_preview_has_a_full_record_entry_without_terminal_locator():
    row = project_transcript_item("turn-1", {
        "aggregatedOutput": "x" * 100_000, "command": "long-running job",
        "type": "commandExecution", "id": "live", "status": "inProgress",
    })[0]
    assert row["contentDeferred"]
    tool = row["tools"][0]
    assert tool["name"] == "Shell" and tool["arg"] == "long-running job"
    assert tool["status"] == "running" and "inspectionLocator" not in tool


def test_normal_chinese_reply_preserves_markdown_instead_of_size_fallback():
    text = "**正常回复**\n" + "内容" * 3000
    row = project_transcript_item("turn-1", {"id": "reply", "type": "agentMessage", "text": text})[0]
    assert row["text"] == text
    assert "contentDeferred" not in row
    assert row["blocks"][0]["text"] == text


@pytest.mark.parametrize("kind", ["userMessage", "reasoning", "agentMessage"])
def test_prose_is_complete_across_fragments_and_former_character_and_byte_caps(kind):
    first, last = "中文😀" * 9000, "**最后一段**\n" * 2000
    fields = {"userMessage": {"content": [{"type": "text", "text": first}, {"type": "text", "text": last}]},
              "reasoning": {"summary": [first], "content": [last]},
              "agentMessage": {"text": first + last}}[kind]
    source = {"id": "prose", "type": kind, **fields}
    row = project_transcript_item("turn-1", bounded_transcript_item(source))[0]
    text = row["text"] if kind != "reasoning" else row["blocks"][0]["thinking"]
    assert first in text and last.strip() in text
    assert "contentDeferred" not in row


def test_single_item_above_page_target_still_loads_whole_without_retry_loop(inspection):
    text = "body\n" * 230_000
    inspection.list_items.return_value = ThreadItemsPage(items=entries(1, text=text), next_cursor="older")
    page = read(inspection)
    assert page["turns"][0]["text"] == text
    assert page["older_cursor"] == "older"
    assert inspection.list_items.call_count == 1


@pytest.mark.parametrize("item", [
    {"type": "commandExecution", "command": "pytest", "aggregatedOutput": "small output", "status": "inProgress"},
    {"type": "mcpToolCall", "tool": "search", "server": "docs", "result": {"content": [{"text": "small output"}]}},
    {"type": "dynamicToolCall", "tool": "lookup", "arguments": {"query": "request"},
     "contentItems": [{"type": "inputText", "text": "small output"}]},
    {"type": "plan", "text": "small output"},
    {"type": "imageView", "path": "/work/plot.png"},
])
def test_every_tool_is_one_header_without_output_even_when_small(item):
    rows = project_transcript_item("turn-1", {"id": "tool", **item})
    assert len(rows) == 1 and rows[0]["contentDeferred"]
    tool = rows[0]["tools"][0]
    assert tool["output"] == []
    assert not {"diff", "media", "commandExecution"} & tool.keys()
    assert "small output" not in json.dumps(rows)


@pytest.mark.parametrize("method, fields, item_id, content_field", [
    ("turn/plan/updated", {"explanation": "complete plan" * 3000}, "turn-1:live-plan", "text"),
    ("turn/diff/updated", {"diff": "+complete change\n" * 3000}, "turn-1:turn-diff", "diff"),
])
def test_live_only_details_are_frozen_and_do_not_search_persisted_history(inspection, method, fields, item_id, content_field):
    inspection.read_model.install_prepared_turns(inspection.read_model.prepare_turn_replacement(
        "thread-1", [], history_mode="paginated"))
    inspection.read_model.apply_notification(method, {"threadId": "thread-1", "turnId": "turn-1", **fields})
    detail = read(inspection, turn_id="turn-1", item_id=item_id, full=True)
    source = json.loads(detail["full_text"])
    assert source[content_field] == next(iter(fields.values()))
    inspection.list_items.assert_not_called()


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


def test_old_server_navigation_scans_only_known_turn_then_reopens_globally(inspection):
    rejection = CodexRpcError("thread/items/list", {"code": -32600,
        "message": "Invalid request: invalid type: map, expected a string"})
    inspection.list_items.side_effect = [rejection, ThreadItemsPage(items=entries(40), next_cursor="scoped-next")]
    result = read(inspection, turn_id="turn-1", item_id="steer")
    assert result["target_pending"] and result["newer_cursor"] == "scoped-next"
    assert result["turns"] == []
    assert all(call.kwargs["turn_id"] == "turn-1" for call in inspection.list_items.call_args_list)
    target = ThreadItemEntry(turn_id="turn-1", item={"id": "steer", "type": "userMessage",
        "content": [{"type": "text", "text": "追加消息"}]})
    following = ThreadItemEntry(turn_id="turn-2", item={"id": "reply", "type": "agentMessage", "text": "next turn"})
    inspection.list_items.reset_mock()
    inspection.list_items.side_effect = [
        ThreadItemsPage(items=[target], backwards_cursor="scoped-inclusive"),
        ThreadItemsPage(items=[target, following], backwards_cursor="global-before", next_cursor="global-after"),
    ]
    result = read(inspection, turn_id="turn-1", item_id="steer", cursor="scoped-next")
    assert not result["target_pending"]
    assert [row["itemId"] for row in result["turns"]] == ["steer", "reply"]
    assert result["older_cursor"] == "global-before" and result["newer_cursor"] == "global-after"
    first, second = inspection.list_items.call_args_list
    assert first.kwargs["turn_id"] == "turn-1" and first.kwargs["cursor"] == "scoped-next"
    assert "anchor_item_id" not in first.kwargs
    assert second.kwargs["cursor"] == "scoped-inclusive"
    assert inspection.list_items.call_args.kwargs["turn_id"] is None


@pytest.mark.parametrize("indexed", [False, True])
def test_missing_target_does_not_reopen_or_scan_unrelated_turns(inspection, indexed):
    start = ThreadItemsPage() if indexed else CodexRpcError("thread/items/list", {
        "code": -32600, "message": "Invalid request: expected a string"})
    inspection.list_items.side_effect = [start, ThreadItemsPage(items=entries(1),
        next_cursor="unrelated" if indexed else None, backwards_cursor="inclusive")]
    with pytest.raises(WebRuntimeError, match="no longer available"):
        read(inspection, turn_id="turn-1", item_id="missing")
    assert inspection.list_items.call_count == 2
    assert all(call.kwargs["turn_id"] == "turn-1" for call in inspection.list_items.call_args_list)


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
