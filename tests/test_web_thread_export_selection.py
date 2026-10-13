"""Selected Q&A exports must preserve whole turns and exact selection."""

from unittest.mock import Mock

import pytest

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage, ThreadTurnsPage
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_export_selection import SummaryExportSelection, decode_export_selection
from bot.web_runtime.thread_summary_export import WebThreadSummaryExportPorts, WebThreadSummaryExportService
from tests.test_web_thread_summary_export import _snapshot


def user(identity, text):
    return {"id": identity, "type": "userMessage", "content": [{"type": "text", "text": text}]}


def answer(identity, text, phase="final_answer"):
    return {"id": identity, "type": "agentMessage", "phase": phase, "text": text}


def turn(identity, *, status="completed", items=None):
    return {"id": identity, "status": status, "items": items if items is not None else [
        user(f"{identity}-u", f"Question {identity}"), answer(f"{identity}-a", f"Reply {identity}"),
    ]}


def service(turn_pages, item_pages=None, *, mode="paginated", **limits):
    def turns(_thread_id, **kwargs):
        key = (kwargs["sort_direction"], kwargs["cursor"], kwargs["items_view"])
        return turn_pages[key]

    def items(_thread_id, **kwargs):
        data, cursor = item_pages[(kwargs["turn_id"], kwargs["cursor"])]
        return ThreadItemsPage(items=[ThreadItemEntry(kwargs["turn_id"], item) for item in data], next_cursor=cursor)

    ports = WebThreadSummaryExportPorts(
        read_thread=Mock(return_value=_snapshot(history_mode=mode)), list_thread_turns=Mock(side_effect=turns),
        list_thread_items=Mock(side_effect=items), capture_connection_generation=lambda: 7,
        run_if_connection_generation=Mock(side_effect=lambda _generation, value: value()),
    )
    return WebThreadSummaryExportService(ports=ports, runtime_context_guard=lambda: None, **limits), ports


def test_selected_turns_use_history_order_and_include_steers_across_item_pages():
    pages = {("asc", None, "summary"): ThreadTurnsPage(turns=[turn("a"), turn("b")], next_cursor="next"),
             ("asc", "next", "summary"): ThreadTurnsPage(turns=[turn("c"), turn("d")])}
    item_pages = {
        ("a", None): ([user("u", "First question"), {"id": "tool", "type": "commandExecution", "output": "SECRET TOOL"}], "items-2"),
        ("a", "items-2"): ([user("steer", "Additional requirement"), answer("p", "SECRET PARTIAL", "partial_answer"),
                             answer("a", "Final A"), answer("comment", "SECRET COMMENT", "commentary")], None),
        ("d", None): ([user("du", "Last question"), answer("da", "Final D")], None),
    }
    exporter, ports = service(pages, item_pages)
    prepared = exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("selected", ("d", "a")))
    markdown = exporter.execute(prepared).decode()
    assert "First question\n\nAdditional requirement" in markdown
    assert markdown.index("Final A") < markdown.index("Final D")
    assert "Question b" not in markdown and "Question c" not in markdown and "SECRET" not in markdown
    assert [call.kwargs["turn_id"] for call in ports.list_thread_items.call_args_list] == ["a", "a", "d"]
    assert all(call.kwargs["expected_connection_generation"] == 7 for call in ports.list_thread_items.call_args_list)
    assert exporter.settle(prepared, markdown.encode()) == markdown.encode()


def test_latest_skips_compaction_turns_and_observes_adapter_page_order():
    pages = {("desc", None, "summary"): ThreadTurnsPage(turns=[turn("old"), turn("new"), turn("compact", items=[])])}
    exporter, ports = service(pages, {("new", None): (turn("new")["items"], None)})
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert b"Question new" in result and b"Question old" not in result
    assert ports.list_thread_turns.call_count == 1


@pytest.mark.parametrize("status", ["inProgress", "interrupted", "failed"])
def test_latest_never_falls_back_past_an_unfinished_question(status):
    exporter, ports = service({("desc", None, "summary"): ThreadTurnsPage(turns=[turn("old"), turn("new", status=status)])})
    with pytest.raises(WebRuntimeError) as error:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert error.value.code == "thread_summary_export_incomplete_turn"
    ports.list_thread_items.assert_not_called()


def test_completed_turn_without_final_does_not_export_partial_answer():
    exporter, _ports = service({("desc", None, "summary"): ThreadTurnsPage(turns=[turn("new")])},
                              {("new", None): ([user("u", "Question"), answer("p", "Partial", "partial_answer")], None)})
    with pytest.raises(WebRuntimeError, match="no final reply"):
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))


def test_phase_unknown_legacy_reply_is_compatible_but_explicit_final_wins():
    exporter, _ports = service({("desc", None, "summary"): ThreadTurnsPage(turns=[turn("new")])},
                              {("new", None): ([user("u", "Question"), answer("a", "Final"), answer("legacy", "Unknown", None)], None)})
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert b"Final" in result and b"Unknown" not in result


def test_missing_selected_turn_fails_without_returning_other_selected_content():
    exporter, _ports = service({("asc", None, "summary"): ThreadTurnsPage(turns=[turn("a")])},
                              {("a", None): (turn("a")["items"], None)})
    with pytest.raises(WebRuntimeError) as error:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("selected", ("a", "gone"))))
    assert error.value.code == "thread_summary_export_missing_turn"


def test_legacy_hydrates_matching_bounded_page_and_keeps_followups():
    full = turn("old", items=[user("u", "Original"), user("steer", "Follow-up"), answer("a", "Legacy reply", None)])
    pages = {("desc", None, "summary"): ThreadTurnsPage(turns=[turn("old")]),
             ("desc", None, "full"): ThreadTurnsPage(turns=[full])}
    exporter, ports = service(pages, mode="legacy")
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert b"Original\n\nFollow-up" in result and b"Legacy reply" in result
    ports.list_thread_items.assert_not_called()


def test_directory_is_bounded_newest_first_and_does_not_load_bodies():
    pages = {("desc", "older", "summary"): ThreadTurnsPage(turns=[turn("a"), turn("b", status="inProgress")], next_cursor="next")}
    exporter, ports = service(pages)
    prepared = exporter.prepare("client-1", "thread-1", cursor="older")
    page = exporter.execute_turns(prepared)
    assert page["thread_id"] == "thread-1" and page["next_cursor"] == "next"
    assert [row["turn_id"] for row in page["turns"]] == ["b", "a"]
    assert page["turns"][0]["status"] == "inProgress"
    assert ports.list_thread_turns.call_args.kwargs["limit"] == 20
    ports.list_thread_items.assert_not_called()
    assert exporter.settle(prepared, page) == page


@pytest.mark.parametrize("payload", [None, {}, {"scope": "all"}, {"scope": "all", "turn_ids": ["a"]},
    {"scope": "selected", "turn_ids": []}, {"scope": "selected", "turn_ids": ["a", "a"]},
    {"scope": "last_turn", "turn_ids": [], "extra": True}, {"scope": "unknown", "turn_ids": []},
    {"scope": "selected", "turn_ids": [None]}, {"scope": "selected", "turn_ids": [" a"]},
    {"scope": "selected", "turn_ids": [str(n) for n in range(101)]}])
def test_rejects_ambiguous_unbounded_or_empty_selection(payload):
    with pytest.raises(WebRuntimeError) as error:
        decode_export_selection(payload)
    assert error.value.code == "invalid_summary_export_selection"


def test_item_cursor_loop_and_output_limit_fail_closed():
    for limit, cursor, code in [(10000, "loop", "thread_summary_export_cursor_loop"),
                                 (10, None, "thread_summary_export_too_large")]:
        pages = {("desc", None, "summary"): ThreadTurnsPage(turns=[turn("a")])}
        items = {("a", None): ([user("u", "A very long question")], cursor),
                 ("a", "loop"): ([answer("a", "Reply")], "loop")}
        exporter, _ports = service(pages, items, max_output_bytes=limit)
        with pytest.raises(WebRuntimeError) as error:
            exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
        assert error.value.code == code
