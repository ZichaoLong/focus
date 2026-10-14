"""Content isolation and history-integrity regressions for browser exports."""

from unittest.mock import Mock

import pytest

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage, ThreadTurnsPage
from bot.adapters.codex_app_server import CodexAppServerAdapter
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_export_selection import SummaryExportSelection, decode_export_selection
from tests.test_web_thread_export_selection import answer, service, turn, user


@pytest.mark.parametrize("mode", ["paginated", "legacy"])
@pytest.mark.parametrize("scope", ["all", "last_turn", "selected"])
@pytest.mark.parametrize("content", ["qa", "final_answers", "prompts"])
def test_content_and_scope_are_independent_and_never_leak_the_excluded_role(mode, scope, content):
    full = [turn(identity, items=[
        user(f"{identity}-u", f"Question {identity}"), user(f"{identity}-steer", f"Follow-up {identity}"),
        answer(f"{identity}-c", "SECRET COMMENTARY", "commentary"),
        answer(f"{identity}-p", "SECRET PARTIAL", "partial_answer"),
        answer(f"{identity}-a", f"Reply {identity}"),
    ]) for identity in ["a", "b"]]
    direction = "desc" if scope == "last_turn" else "asc"
    pages = {(direction, None, "summary"): ThreadTurnsPage(turns=[turn("a"), turn("b")]),
             (direction, None, "full"): ThreadTurnsPage(turns=full)}
    exporter, _ports = service(pages, {(row["id"], None): (row["items"], None) for row in full}, mode=mode)
    selection = SummaryExportSelection(scope, ("b", "a") if scope == "selected" else (), content)
    markdown = exporter.execute(exporter.prepare("client-1", "thread-1", selection=selection)).decode()
    identities = ["b"] if scope == "last_turn" else ["a", "b"]
    assert "SECRET" not in markdown
    for identity in identities:
        assert (f"Question {identity}" in markdown) == (content != "final_answers")
        assert (f"Reply {identity}" in markdown) == (content != "prompts")
        assert (f"Follow-up {identity}" in markdown) == (content == "prompts" or (content == "qa" and scope != "all"))
    assert ("### User" in markdown) == (content != "final_answers")
    assert ("### Assistant" in markdown) == (content != "prompts")
    if scope != "last_turn":
        label = "Reply" if content == "final_answers" else "Question"
        assert markdown.index(f"{label} a") < markdown.index(f"{label} b")
    else:
        assert "Question a" not in markdown and "Reply a" not in markdown


@pytest.mark.parametrize("status", ["inProgress", "interrupted", "failed"])
@pytest.mark.parametrize("scope", ["all", "last_turn", "selected"])
def test_prompts_can_export_unfinished_turns_and_all_followups(status, scope):
    direction = "desc" if scope == "last_turn" else "asc"
    pages = {(direction, None, "summary"): ThreadTurnsPage(turns=[turn("new", status=status)])}
    exporter, _ports = service(pages, {("new", None): ([user("u", "Question"), user("s", "Follow-up"),
                                                       answer("p", "SECRET PARTIAL", "partial_answer")], None)})
    selection = SummaryExportSelection(scope, ("new",) if scope == "selected" else (), "prompts")
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=selection))
    assert b"Question\n\nFollow-up" in result and b"SECRET" not in result


def test_all_prompts_scans_every_page_instead_of_returning_after_the_first_turn():
    pages = {("asc", None, "summary"): ThreadTurnsPage(turns=[turn("a")], next_cursor="older"),
             ("asc", "older", "summary"): ThreadTurnsPage(turns=[turn("b")])}
    exporter, _ports = service(pages, {(identity, None): (turn(identity)["items"], None) for identity in ["a", "b"]})
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection(content="prompts")))
    assert b"Question a" in result and b"Question b" in result and b"Reply" not in result


def test_all_final_replies_skips_unfinished_and_unanswered_turns_without_prompt_headings():
    pages = {("asc", None, "summary"): ThreadTurnsPage(turns=[
        turn("a"), turn("running", status="inProgress"), turn("failed", status="failed"),
        turn("partial", items=[user("u", "Question partial"), answer("p", "SECRET", "partial_answer")]),
    ])}
    exporter, ports = service(pages)
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection(content="final_answers")))
    assert b"Reply a" in result and b"Question" not in result and b"running" not in result and b"SECRET" not in result
    ports.list_thread_items.assert_not_called()


def test_all_qa_does_not_treat_an_unfinished_phase_null_message_as_a_final_reply():
    pending = turn("pending", status="inProgress", items=[user("u", "Question"), answer("a", "SECRET DRAFT", None)])
    exporter, _ports = service({("asc", None, "summary"): ThreadTurnsPage(turns=[pending])})
    result = exporter.execute(exporter.prepare("client-1", "thread-1"))
    assert b"Question" in result and b"SECRET" not in result and b"### Assistant" not in result


def test_all_qa_rejects_repeated_turns_across_pages_instead_of_duplicating_content():
    pages = {("asc", None, "summary"): ThreadTurnsPage(turns=[turn("a")], next_cursor="again"),
             ("asc", "again", "summary"): ThreadTurnsPage(turns=[turn("a")])}
    exporter, _ports = service(pages)
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1"))
    assert failure.value.code == "thread_summary_export_protocol_error"


@pytest.mark.parametrize("scope", ["last_turn", "selected"])
def test_final_replies_do_not_fall_back_past_an_unfinished_chosen_turn(scope):
    direction = "desc" if scope == "last_turn" else "asc"
    exporter, ports = service({(direction, None, "summary"): ThreadTurnsPage(turns=[turn("old"), turn("new", status="inProgress")])})
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection(
            scope, ("new",) if scope == "selected" else (), "final_answers")))
    assert failure.value.code == "thread_summary_export_incomplete_turn"
    ports.list_thread_items.assert_not_called()


@pytest.mark.parametrize("content", ["prompts", "final_answers"])
def test_empty_role_export_fails_instead_of_downloading_an_empty_document(content):
    exporter, _ports = service({("asc", None, "summary"): ThreadTurnsPage(turns=[turn("system", items=[])])})
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection(content=content)))
    assert failure.value.code == "thread_summary_export_missing_content"


@pytest.mark.parametrize("payload", [
    {"scope": "all", "turn_ids": []},
    {"scope": "all", "turn_ids": [], "content": "unknown"},
    {"scope": "all", "turn_ids": [], "content": None},
])
def test_content_is_exact_and_required_on_the_wire(payload):
    with pytest.raises(WebRuntimeError, match="qa, final_answers, or prompts"):
        decode_export_selection(payload)


@pytest.mark.parametrize("raw_page", [
    {"data": [None, turn("old")], "nextCursor": None},
    *[{"data": [turn("old")], "nextCursor": cursor} for cursor in [False, 123, [], "", " cursor "]],
])
def test_real_adapter_does_not_hide_a_malformed_latest_turn_or_cursor(raw_page):
    exporter, ports = service({})
    ports.list_thread_turns.side_effect = lambda _thread_id, **kwargs: CodexAppServerAdapter._turns_page_from_result(
        raw_page, sort_direction=kwargs["sort_direction"])
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert failure.value.code == "thread_summary_export_protocol_error"
    ports.list_thread_items.assert_not_called()


@pytest.mark.parametrize("entries", [
    [ThreadItemEntry("other-turn", user("u", "FOREIGN"))],
    [ThreadItemEntry("new", user("duplicate", "Question")), ThreadItemEntry("new", answer("duplicate", "Reply"))],
])
def test_selected_export_rejects_foreign_or_duplicate_items(entries):
    exporter, ports = service({("desc", None, "summary"): ThreadTurnsPage(turns=[turn("new")])})
    ports.list_thread_items.side_effect = None
    ports.list_thread_items.return_value = ThreadItemsPage(items=entries)
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert failure.value.code == "thread_summary_export_protocol_error"


def test_selected_export_checks_the_total_deadline_after_item_reads():
    now = [0.0]
    exporter, ports = service({("desc", None, "summary"): ThreadTurnsPage(turns=[turn("new")])}, monotonic=lambda: now[0])

    def slow_items(*_args, **_kwargs):
        now[0] = 31.0
        return ThreadItemsPage(items=[ThreadItemEntry("new", item) for item in turn("new")["items"]])

    ports.list_thread_items.side_effect = slow_items
    with pytest.raises(WebRuntimeError) as failure:
        exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert failure.value.code == "thread_summary_export_timeout"


def test_real_adapter_preserves_descending_page_order_before_last_turn_selection():
    exporter, ports = service({}, {("new", None): (turn("new")["items"], None)})
    ports.list_thread_turns.side_effect = Mock(return_value=CodexAppServerAdapter._turns_page_from_result(
        {"data": [turn("compact", items=[]), turn("new"), turn("old")], "nextCursor": None}, sort_direction="desc"))
    result = exporter.execute(exporter.prepare("client-1", "thread-1", selection=SummaryExportSelection("last_turn")))
    assert b"Question new" in result and b"Question old" not in result
