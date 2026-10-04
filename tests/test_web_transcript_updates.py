"""Large-turn live-cache and coalesced item-publication regression evidence."""
from dataclasses import replace

from bot.web_runtime.thread_read_model import WebThreadReadModel
from bot.web_runtime.transcript_window import project_transcript_item
from tests import test_web_runtime_event_coordinator as support
from tests import test_web_thread_open_coordinator as open_support


def model():
    result = WebThreadReadModel()
    result.install_prepared_turns(result.prepare_turn_replacement("root-1", [], history_mode="paginated"))
    return result


def item(index, text="content"):
    return {"id": f"item-{index}", "type": "agentMessage", "text": text}


def coordinator():
    scheduled = []
    owner, peers, callbacks = support.WebRuntimeEventCoordinatorTests()._build(schedule_projection=scheduled.append)
    cache = model()
    owner._ports = replace(owner._ports, read_model=cache)
    peers.runtime_interest.has_managed_interest.return_value = True
    return owner, cache, scheduled, callbacks


def test_thousands_of_items_keep_fixed_cache_and_summary_refresh_preserves_live_text():
    cache = model()
    cache.apply_notification("turn/started", {"threadId": "root-1", "turn": {
        "id": "turn-1", "status": "inProgress", "items": [item(i) for i in range(5000)],
    }})
    turn = cache.cached_turn("root-1", "turn-1")
    assert len(turn["items"]) == 80
    assert turn["items"][0]["id"] == "item-4920"
    cache.install_prepared_turns(cache.prepare_turn_replacement("root-1", [{
        "id": "turn-1", "status": "inProgress", "items": [],
    }], history_mode="paginated", summary_only=True))
    cache.apply_notification("item/agentMessage/delta", {"threadId": "root-1", "turnId": "turn-1",
        "itemId": "item-4999", "delta": " streamed"})
    assert cache.cached_turn("root-1", "turn-1")["items"][-1]["text"] == "content streamed"
    assert cache.cached_active_turn_id("root-1") == "turn-1"


def test_published_payload_contains_only_changed_items_with_bounded_order():
    owner, cache, scheduled, callbacks = coordinator()
    owner.handle_notification("turn/started", {"threadId": "root-1", "turn": {
        "id": "turn-1", "status": "inProgress", "items": [item(i) for i in range(80)],
    }})
    first = scheduled.pop()
    owner.settle_notification_projection(first, owner.project_notification(first))
    callbacks.publish_projection.reset_mock()
    owner.handle_notification("item/completed", {"threadId": "root-1", "turnId": "turn-1", "item": item(80)})
    second = scheduled.pop()
    owner.settle_notification_projection(second, owner.project_notification(second))
    payload = callbacks.publish_projection.call_args.kwargs["detail"]
    assert len(payload["item_order"]) == 80
    assert [row["itemId"] for row in payload["item_turns"]] == ["item-80"]
    assert len(cache.cached_turn("root-1", "turn-1")["items"]) == 80


def test_successor_uses_latest_cache_after_streams_instead_of_rolling_back_text():
    owner, _, scheduled, callbacks = coordinator()
    owner.handle_notification("item/started", {"threadId": "root-1", "turnId": "turn-1", "item": item(1, "start")})
    old = scheduled[0]
    for _ in range(20):
        owner.handle_notification("item/agentMessage/delta", {"threadId": "root-1", "turnId": "turn-1",
            "itemId": "item-1", "delta": "!"})
    assert len(scheduled) == 1
    assert old.update.raw_turn["items"][0]["text"] == "start"
    callbacks.publish_projection.reset_mock()
    owner.settle_notification_projection(old, owner.project_notification(old))
    callbacks.publish_projection.assert_not_called()
    fresh = scheduled[1]
    owner.settle_notification_projection(fresh, owner.project_notification(fresh))
    payload = callbacks.publish_projection.call_args.kwargs["detail"]
    assert payload["item_turns"][0]["text"] == "start" + "!" * 20


def test_reply_timing_survives_completion_coalescing_and_turn_snapshot_replacement():
    owner, cache, scheduled, callbacks = coordinator()
    params = {"threadId": "root-1", "turnId": "turn-1", "item": item(1, "start")}
    owner.handle_notification("item/started", {**params, "startedAtMs": 123_000})
    old = scheduled.pop()
    owner.handle_notification("item/completed", {**params, "completedAtMs": 126_000, "item": item(1, "answer" * 10_000)})
    owner.settle_notification_projection(old, owner.project_notification(old))
    fresh = scheduled.pop()
    owner.settle_notification_projection(fresh, owner.project_notification(fresh))
    row = callbacks.publish_projection.call_args.kwargs["detail"]["item_turns"][0]
    assert row["reply"] == {"state": "complete", "startedAtMs": 123_000, "completedAtMs": 126_000}
    assert row["text"] == "answer" * 10_000
    assert "contentDeferred" not in row
    cache.apply_notification("turn/completed", {"threadId": "root-1", "turn": {
        "id": "turn-1", "status": "completed", "startedAt": 1,
        "items": [item(1, "answer" * 10_000)],
    }})
    stored = cache.cached_turn("root-1", "turn-1")["items"][0]
    assert project_transcript_item("turn-1", stored)[0]["reply"] == row["reply"]


def test_partial_live_timing_does_not_borrow_the_turn_or_arrival_time():
    cache = model()
    cache.apply_notification("item/started", {"threadId": "root-1", "turnId": "turn-1",
        "startedAtMs": "invalid", "item": item(1)})
    stored = cache.cached_turn("root-1", "turn-1")["items"][0]
    assert project_transcript_item("turn-1", stored)[0]["reply"] == {"state": "generating"}
    assert project_transcript_item("turn-1", stored, status="completed")[0]["reply"] == {"state": "unknown"}
    cache.apply_notification("item/completed", {"threadId": "root-1", "turnId": "turn-1",
        "completedAtMs": 15_000, "item": item(1)})
    stored = cache.cached_turn("root-1", "turn-1")["items"][0]
    assert project_transcript_item("turn-1", stored)[0]["reply"] == {"state": "complete", "completedAtMs": 15_000}


def test_live_prose_stays_complete_and_unopened_tool_logs_are_not_published():
    owner, cache, scheduled, callbacks = coordinator()
    text = "正文😀" * 10_000
    owner.handle_notification("item/started", {"threadId": "root-1", "turnId": "turn-1", "item": item(1, text)})
    first = scheduled.pop()
    owner.settle_notification_projection(first, owner.project_notification(first))
    cache.apply_notification("item/agentMessage/delta", {"threadId": "root-1", "turnId": "turn-1",
        "itemId": "item-1", "delta": "最后追加"})
    assert cache.cached_turn("root-1", "turn-1")["items"][0]["text"] == text + "最后追加"
    callbacks.publish_projection.reset_mock()
    for method in ("item/commandExecution/outputDelta", "item/fileChange/outputDelta", "item/mcpToolCall/progress"):
        owner.handle_notification(method, {"threadId": "root-1", "turnId": "turn-1", "itemId": "tool",
            "delta": "unopened log" * 10_000, "message": "unopened progress"})
    callbacks.publish_projection.assert_not_called()


def test_live_cache_evicts_whole_older_items_instead_of_clipping_the_current_one():
    cache = model()
    text = "content" * 100_000
    cache.apply_notification("turn/started", {"threadId": "root-1", "turn": {
        "id": "turn-1", "status": "inProgress", "items": [item(i, text) for i in range(10)],
    }})
    stored = cache.cached_turn("root-1", "turn-1")["items"]
    assert 1 < len(stored) < 10
    assert stored[-1]["id"] == "item-9"
    assert all(entry["text"] == text for entry in stored)


def test_control_summary_refresh_keeps_observed_collaboration_tasks():
    case = open_support.WebThreadOpenCoordinatorTests(methodName="runTest")
    case.setUp()
    try:
        case.fake.history_mode = "paginated"
        case.fake.turns = [{"id": "turn-1", "status": "inProgress", "items": []}]
        case.open.read_thread("tab-1", "thread-1")
        cache = case.controller._thread_read_model
        cache.apply_notification("item/completed", {"threadId": "thread-1", "turnId": "turn-1", "item": {
            "id": "spawn", "type": "collabAgentToolCall", "tool": "spawnAgent", "status": "completed",
            "receiverThreadIds": ["child-1"], "prompt": "Inspect", "agentsStates": {
                "child-1": {"status": "running", "message": "Working"},
            },
        }})
        result = case.open.read_thread("tab-1", "thread-1")
        assert [task["id"] for task in result["tasks"]] == ["child-1"]
        assert result["turns"] == []
    finally:
        case.doCleanups()


def test_final_item_can_be_published_only_with_the_coalesced_turn_completion():
    owner, _, scheduled, callbacks = coordinator()
    params = {"threadId": "root-1", "turnId": "turn-1"}
    owner.handle_notification("item/started", {**params, "item": item(1, "")})
    owner.handle_notification("item/completed", {**params, "item": item(1, "final answer")})
    owner.handle_notification("turn/completed", {"threadId": "root-1", "turn": {
        "id": "turn-1", "status": "completed", "items": [],
    }})
    callbacks.publish_projection.reset_mock()
    while scheduled:
        receipt = scheduled.pop(0)
        owner.settle_notification_projection(receipt, owner.project_notification(receipt))
    callbacks.publish_projection.assert_called_once()
    payload = callbacks.publish_projection.call_args.kwargs["detail"]
    assert payload["method"] == "turn/completed"
    assert payload["item_turns"][0]["text"] == "final answer"
    assert payload["item_order"] == ["turn-1:item:item-1:0"]
