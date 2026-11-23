"""Paginated upstream fixture for force-stop and offline reader acceptance."""

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage


def install_record_history(fake, instance: int) -> None:
    fake.history_mode = "paginated"
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
        if thread_id != "thread-1":
            return ThreadItemsPage()
        items = [ThreadItemEntry(turn["id"], item) for turn in turns for item in turn["items"]]
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
