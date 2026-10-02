"""Large-turn live-cache and coalesced item-publication regression evidence."""
from dataclasses import replace

from bot.web_runtime.thread_read_model import WebThreadReadModel
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
