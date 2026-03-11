---
name: send
description: Send a Slack message to a channel or DM. Use when the user says "send slack", "slack message", "post to slack", or wants to send a message to a Slack channel.
---

# Send Slack Message

Send a message to a Slack channel or DM.

## Arguments

- `channel` — channel name or ID (e.g., `general`, `C01ABC123`). Falls back to `DEFAULT_CHANNEL` from config.
- `message` — the message text to send

## Steps

1. Use the `scc-slack:config` skill to load plugin config. If no channel was specified, use `DEFAULT_CHANNEL`.

2. If you already have the channel and message from conversation context (e.g., replying to a read message), send directly — skip to step 4.

3. Otherwise, ask the user for any missing fields (channel, message).

4. **Resolve @mentions in the message.** If the message contains `@name` patterns (e.g., `@rogue1`, `@christo`), use the `scc-slack:lookup` skill to resolve each name to a user ID. Replace `@name` with `<@USER_ID>` in the message text. If no match is found, warn and send as-is.

5. Send the message (uses CLI — token is read automatically):
   ```bash
   slack chat send --text "<message>" --channel "<channel>"
   ```

6. Confirm delivery with the channel name.
