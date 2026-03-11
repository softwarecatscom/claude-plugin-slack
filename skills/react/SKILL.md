---
name: react
description: React to a Slack message with an emoji. Use when the user says "react", "add emoji", "thumbs up that", or wants to add a reaction to a message.
---

# React to Slack Message

Add an emoji reaction to the most recently read message.

## Arguments

- `emoji` — emoji name without colons (e.g., `thumbsup`, `eyes`, `white_check_mark`)
- `author` — (optional) if the user specifies a message by author name (e.g., "react to rogue1's message"), resolve the name and find their most recent message in the channel

## Steps

1. Use the `scc-slack:token` skill to load `SLACK_TOKEN`.

2. Get the last-read message timestamp and channel from `~/.claude/slack-cursors.conf`. The most recently updated entry is the target.

3. **If an author name was specified**, use the `scc-slack:lookup` skill to resolve the name to a user ID, then scan the recently fetched messages for one with a matching `.user` field.

4. Add the reaction (no CLI equivalent — uses curl):
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"timestamp\":\"$MESSAGE_TS\",\"name\":\"$EMOJI\"}" \
     https://slack.com/api/reactions.add
   ```

5. Confirm the reaction was added.
