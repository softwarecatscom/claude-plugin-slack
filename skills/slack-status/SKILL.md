---
name: status
description: Set Slack status text and emoji. Use when the user says "set slack status", "update status", "change presence", or wants to update their Slack status.
---

# Set Slack Status

Set the bot's Slack profile status text and emoji.

## Arguments

- `text` — status text (e.g., "In a meeting", "Working on deploy")
- `emoji` — status emoji without colons (optional, defaults to `speech_balloon`)

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. Set the status:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"profile\":{\"status_text\":\"$TEXT\",\"status_emoji\":\":$EMOJI:\"}}" \
     https://slack.com/api/users.profile.set
   ```

3. Confirm the status was updated.
