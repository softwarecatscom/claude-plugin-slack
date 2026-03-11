---
name: slack-tidy
description: Reset Slack cursor state and mark channels as read. Use when the user says "tidy slack", "reset slack cursors", "mark all read", or wants to clean up Slack tracking state.
---

# Tidy Slack State

Reset cursor tracking state and optionally mark all channels as read.

## Steps

1. Show current cursor state:
   ```bash
   echo "Tracked channels:"
   cat ~/.claude/slack-cursors.conf 2>/dev/null || echo "(none)"
   ```

2. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

3. For each tracked channel, mark as read in Slack:
   ```bash
   while IFS='=' read -r CHANNEL_ID TIMESTAMP; do
     curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
       -H "Content-type: application/json" \
       -d "{\"channel\":\"$CHANNEL_ID\",\"ts\":\"$TIMESTAMP\"}" \
       https://slack.com/api/conversations.mark
   done < ~/.claude/slack-cursors.conf
   ```

4. Reset the cursor file:
   ```bash
   > ~/.claude/slack-cursors.conf
   ```

5. Report what was tidied (number of channels reset).
