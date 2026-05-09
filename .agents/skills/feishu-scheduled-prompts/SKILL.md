---
name: feishu-scheduled-prompts
description: Use when the user wants a future one-shot or recurring task to continue the current Feishu-bound Codex thread later. This skill manages Linux systemd --user timers that eventually call feishu-codexctl prompt send back into the bound Feishu session.
---

# Feishu Scheduled Prompts

Use this skill when the user wants:

- "tomorrow morning continue this thread"
- "every trading day at 15:25 send a market recap into this Feishu chat"
- "list / remove / run now the scheduled tasks for this workspace"

This skill is intentionally narrow:

- it manages `systemd --user` timers on Linux
- it always routes execution back through `feishu-codexctl prompt send`
- it does not create a second Codex backend

Do not use it for:

- background loops or always-on daemons
- cross-machine scheduling
- vague "remind me somewhere later" requests without a concrete Feishu-bound thread target

Workflow:

1. Confirm you are in a Codex turn with `CODEX_THREAD_ID` available.
2. Resolve the current thread's attached Feishu binding:
   - run `feishu-codexctl thread bindings --thread-id "$CODEX_THREAD_ID"`
   - if there is exactly one `[attached]` binding, use it
   - if there are zero attached bindings, stop and tell the user there is no attached Feishu chat to receive scheduled output
   - if there are multiple attached bindings, ask the user which one should receive the scheduled task
3. Resolve the owning instance for that thread:
   - prefer `feishu-codexctl thread status --thread-id "$CODEX_THREAD_ID"` and read `live runtime owner`
   - if the owner is `none`, ask the user which instance should own future scheduled execution
4. Convert the user's desired time into a concrete `systemd` `OnCalendar=` expression.
5. Use the helper script in this skill:

   ```bash
   python3 scripts/manage_scheduled_prompt.py create \
     --task-id "<short-stable-id>" \
     --instance "<instance-name>" \
     --binding-id "<binding-id>" \
     --on-calendar "<systemd OnCalendar expression>" \
     --prompt-file "<utf8-text-file>"
   ```

6. For inspection / cleanup, use:

   ```bash
   python3 scripts/manage_scheduled_prompt.py list
   python3 scripts/manage_scheduled_prompt.py show --task-id "<task-id>"
   python3 scripts/manage_scheduled_prompt.py remove --task-id "<task-id>"
   python3 scripts/manage_scheduled_prompt.py run-now --task-id "<task-id>"
   ```

Rules:

- Prefer `--prompt-file` over inline prompt text when the prompt is more than one short sentence.
- Keep task ids short, ASCII, and stable, for example `ashare-close-recap`.
- Default to `--synthetic-source schedule` and `--display-mode silent` unless the user explicitly wants an announcement message before execution.
- Treat helper failures as authoritative. Do not paper over `systemctl --user` or control-plane errors.
- Do not try to auto-pick a binding when multiple attached bindings exist.

When reporting back, include:

- the task id
- the target binding id
- the `OnCalendar` expression
- whether it was created, updated, removed, listed, or run immediately
