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

1. Load plugin config:
   ```bash
   cat ~/.claude/slack.conf 2>/dev/null
   ```
   If the config is missing and no channel was specified, tell the user to run `/scc-slack:setup` first.

2. If you already have the channel and message from conversation context (e.g., replying to a read message), send directly — skip to step 4.

3. Otherwise, ask the user for any missing fields (channel, message).

4. Send the message (uses CLI — token is read automatically):
   ```bash
   slack chat send --text "<message>" --channel "<channel>"
   ```

5. Confirm delivery with the channel name.
