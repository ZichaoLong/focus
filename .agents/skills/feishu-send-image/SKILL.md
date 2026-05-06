---
name: feishu-send-image
description: Use when Codex needs to send a concrete local image file back to the Feishu chats attached to the current thread. This is the primary outbound-image path for files Codex created, downloaded, or edited locally. Prefer it over depending on upstream imageGeneration behavior. Inside a Codex turn, it may rely on CODEX_THREAD_ID; otherwise pass --thread-id or --thread-name explicitly.
---

# Feishu Send Image

Use this skill only when there is already a real local image file to send.

Do not use it for:

- scanning the workspace for possible images
- non-image files
- guessing a target thread from prompt text alone

Workflow:

1. Confirm the local file path exists.
2. Prefer the explicit control-plane command:

   ```bash
   feishu-codexctl image send --path "<local-image-path>"
   ```

3. If `CODEX_THREAD_ID` is not available in the current environment, use an explicit thread selector:

   ```bash
   feishu-codexctl image send --path "<local-image-path>" --thread-id <thread-id>
   ```

   or

   ```bash
   feishu-codexctl image send --path "<local-image-path>" --thread-name "<thread-name>"
   ```

4. Treat command failures as authoritative:
   - "no attached binding" means no Feishu chat is currently attached to that thread
   - partial delivery means some bindings already received the image; retry is not guaranteed to be idempotent

When reporting back to the user, include:

- the image path you sent
- whether delivery was full or partial
- any binding-level failure if the command reported one
