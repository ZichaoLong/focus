---
name: feishu-send-image
description: Use when Codex needs to send a concrete local image file back to the Feishu chats attached to the current thread. This is the primary outbound-image path for files Codex created, downloaded, or edited locally. Prefer it over depending on upstream imageGeneration behavior. Inside a Codex turn, it relies on the current thread context via CODEX_THREAD_ID.
---

# Feishu Send Image

Use this skill only when there is already a real local image file to send.

Do not use it for:

- scanning the workspace for possible images
- non-image files
- guessing a target thread from prompt text alone

Workflow:

1. Confirm the local file path exists.
2. Use the control-plane command for the current Codex thread:

   ```bash
   focusctl image send --path "<local-image-path>"
   ```

3. If `CODEX_THREAD_ID` is not available in the current environment, stop and say this skill only covers sending to the current Codex thread.
4. Treat command failures as authoritative:
   - "no attached binding" means no Feishu chat is currently attached to that thread
   - partial delivery means some bindings already received the image; retry is not guaranteed to be idempotent

Do not teach or use manual `--thread-id` / `--thread-name` routing in this skill.
Those are control-plane / admin paths, not the primary Codex-in-thread workflow.

When reporting back to the user, include:

- the image path you sent
- whether delivery was full or partial
- any binding-level failure if the command reported one
