---
name: read
description: Read new Slack messages from a channel. Use when the user says "check slack", "read slack", "any slack messages", or wants to see recent channel messages.
---

# Read Slack Messages

Read new messages from a Slack channel. **These messages are for you, the agent.** Read them, understand them, and act on them autonomously. Do NOT ask the user if they want to reply — just handle each message yourself. Only involve the user when you genuinely cannot proceed without their input.

## Arguments

- `channel` — channel name or ID (optional, defaults to `DEFAULT_CHANNEL` from config)

## Steps

1. Load token and plugin config:
   ```bash
   SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack")
   ```
   ```bash
   cat ~/.claude/slack.conf 2>/dev/null
   ```
   Parse `DEFAULT_CHANNEL` and `AUTONOMOUS_CHANNELS` from the config output.

2. Determine the channel. If none specified, use `DEFAULT_CHANNEL` from config.

3. Get the channel ID via the Slack API (the CLI has no `channels list` command):
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.list?types=public_channel&limit=200" \
     | jq -r '.channels[] | "\(.id) \(.name)"' | grep "<channel>"
   ```

4. Read the last cursor timestamp for this channel:
   ```bash
   CURSOR=$(grep "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf 2>/dev/null | cut -d= -f2)
   ```

5. Fetch new messages since the cursor:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.history?channel=$CHANNEL_ID&oldest=$CURSOR&limit=20" \
     | jq '.messages[] | "\(.user // .bot_id): \(.text)"'
   ```
   If no cursor exists, fetch the last 10 messages.

6. If messages were returned, store the newest timestamp as the new cursor:
   ```bash
   NEWEST=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.history?channel=$CHANNEL_ID&oldest=$CURSOR&limit=20" \
     | jq -r '.messages[0].ts')
   grep -v "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf > /tmp/slack-cursors.tmp 2>/dev/null
   echo "$CHANNEL_ID=$NEWEST" >> /tmp/slack-cursors.tmp
   mv /tmp/slack-cursors.tmp ~/.claude/slack-cursors.conf
   ```

7. Update Slack's read marker:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"ts\":\"$NEWEST\"}" \
     https://slack.com/api/conversations.mark
   ```

8. **Act on each message:**
   - If it's a question you can answer, reply via slack-send
   - If it requires action (run a command, check something), do it and reply with the result
   - If it's informational, acknowledge it
   - If you need the user's input to proceed, summarize the message and ask them

9. If no new messages, say nothing (stay quiet to avoid noise).
