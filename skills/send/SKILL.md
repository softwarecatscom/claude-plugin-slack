---
name: send
description: Send a Slack message to a channel or DM. Use when the user says "send slack", "slack message", "post to slack", or wants to send a message to a Slack channel.
---

# Send Slack Message

Send a message to a Slack channel or DM.

## Arguments

- `channel` — channel name or ID (e.g., `general`, `C01ABC123`). Falls back to `DEFAULT_CHANNEL` from config.
- `message` — the message text to send

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

**ALWAYS use `slack-send` to post messages.** Do NOT call `chat.postMessage` directly with curl. The script handles token loading, channel resolution, `@Name` → `<@USERID>` mention resolution, and broadcast encoding (`@here` → `<!here>`). Calling the API directly bypasses this and introduces bugs.

## Steps

1. Use the `scc-slack:config` skill to load plugin config. If no channel was specified, use `DEFAULT_CHANNEL`.

2. If you already have the channel and message from conversation context (e.g., replying to a read message), skip to step 4.

3. Otherwise, ask the user for any missing fields (channel, message).

4. Send the message. The script auto-resolves `@Name` to `<@USERID>` and channel names to IDs:
   ```bash
   "${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "${MESSAGE}"
   ```

5. Confirm delivery with the channel name.
