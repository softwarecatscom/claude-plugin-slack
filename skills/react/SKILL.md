---
name: react
description: React to a Slack message with an emoji. Use when the user says "react", "add emoji", "thumbs up that", or wants to add a reaction to a message.
---

# React to Slack Message

Add an emoji reaction to the most recently read message.

## Arguments

- `emoji` — emoji name without colons (e.g., `thumbsup`, `eyes`, `white_check_mark`)

## Steps

1. Load token:
   ```bash
   SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack")
   ```

2. Get the last-read message timestamp and channel from `~/.claude/slack-cursors.conf`. The most recently updated entry is the target.

3. Add the reaction (no CLI equivalent — uses curl):
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"timestamp\":\"$MESSAGE_TS\",\"name\":\"$EMOJI\"}" \
     https://slack.com/api/reactions.add
   ```

4. Confirm the reaction was added.
