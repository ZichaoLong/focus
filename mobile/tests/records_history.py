"""Paginated upstream fixture for force-stop and offline reader acceptance."""

from dataclasses import replace

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage
from bot.codex_protocol.client import CodexRpcError


def install_record_history(fake, instance: int, arrival=None) -> None:
    fake.history_mode = "paginated"
    read_thread = fake.read_thread

    def read(thread_id, include_turns, **options):
        if thread_id == "fixture-external-gone":
            raise CodexRpcError("thread/read", {"message": f"thread not loaded: {thread_id}"})
        if thread_id == "fixture-archived":
            snapshot = read_thread("thread-1", include_turns, **options)
            return replace(snapshot, summary=replace(snapshot.summary, thread_id=thread_id,
                           path=f"/data/archived_sessions/{thread_id}"))
        return read_thread(thread_id, include_turns, **options)

    fake.read_thread = read
    turns = [
        {"id": f"turn-{n}", "status": "completed", "items": [
            {"type": "userMessage", "id": f"q-{n}", "content": [{"type": "text", "text": f"site-{instance} question {n}"}]},
            {"type": "agentMessage", "id": f"a-{n}", "text": f"site-{instance} answer {n}\n" + "测试段落 🌿。" * 30},
        ]}
        for n in range(230)
    ]
    tail = turns[-1]["items"]
    for group in ("left", "right"):
        tail.extend({"id": f"{group}-{i}", "type": "commandExecution", "command": f"{group} command {i}",
                     "status": "completed", "aggregatedOutput": f"private-output-{group}-{i}"} for i in range(80))
        tail.append({"id": group, "type": "agentMessage", "text": f"{group} reply"})
    fake.turns = turns

    def page(thread_id, **options):
        if thread_id == "thread-2":
            items=[ThreadItemEntry("other-turn",{"id":"other-reply","type":"agentMessage","text":"First visit saved immediately"})]
        elif thread_id == "thread-1":
            items = [ThreadItemEntry(turn["id"], item) for turn in turns for item in turn["items"]]
            if arrival is not None and arrival.exists():
                items.append(ThreadItemEntry("turn-230",{"id":"after-reopen","type":"agentMessage","text":"**Arrived while away**"}))
        else:
            return ThreadItemsPage()
        step = 1 if options["sort_direction"] == "asc" else -1
        cursor = options.get("cursor")
        start = int(cursor) - (step < 0) if cursor is not None else (0 if step == 1 else len(items)-1)
        if options.get("anchor_item_id"):
            start = next(i for i, entry in enumerate(items) if entry.item["id"] == options["anchor_item_id"]) + step
        indices = [i for i in range(start, len(items) if step == 1 else -1, step)
                   if not options.get("turn_id") or items[i].turn_id == options["turn_id"]]
        batch = indices[:options["limit"]]
        if not batch:
            return ThreadItemsPage()
        following = len(indices) > len(batch)
        return ThreadItemsPage([items[i] for i in batch],
                               str(batch[-1] + (step == 1)) if following else None,
                               str(batch[0] + (step < 0)))

    fake.list_thread_items = page
