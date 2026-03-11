---
name: react
description: React to a Slack message with an emoji. Use when the user says "react", "add emoji", "thumbs up that", or wants to add a reaction to a message.
---

# React to Slack Message

Add an emoji reaction to the most recently read message.

## Arguments

- `emoji` — emoji name without colons (e.g., `thumbsup`, `eyes`, `white_check_mark`)
- `author` — (optional) if the user specifies a message by author name (e.g., "react to rogue1's message"), resolve the name and find their most recent message in the channel

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Steps

1. Use the `scc-slack:token` skill to load `SLACK_TOKEN`.

2. Get the last-read message timestamp and channel from `~/.claude/slack-cursors.conf`. The most recently updated entry is the target:
   ```bash
   tail -1 ~/.claude/slack-cursors.conf | IFS='=' read -r CHANNEL_ID MESSAGE_TS
   ```

3. **If an author name was specified**, resolve to a user ID:
   ```bash
   "${SCRIPTS_DIR}/slack-resolve" --name "<author_name>"
   ```
   Then scan the recently fetched messages for one with a matching `.user` field.

4. Add the reaction:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"timestamp\":\"$MESSAGE_TS\",\"name\":\"$EMOJI\"}" \
     https://slack.com/api/reactions.add
   ```

5. Confirm the reaction was added.
