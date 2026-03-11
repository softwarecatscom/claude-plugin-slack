---
name: channels
description: List Slack channels the bot has access to. Use when the user says "list channels", "slack channels", "what channels", or wants to see available Slack channels.
---

# List Slack Channels

List all public channels (and private channels if `groups:read` scope is granted).

## Steps

1. Load token and plugin config:
   ```bash
   SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack")
   ```
   ```bash
   cat ~/.claude/slack.conf 2>/dev/null
   ```
   If the token file is missing, tell the user to run `/scc-slack:setup` first.

2. List channels via the Slack API (the CLI has no channels command). Try public+private first, fall back to public-only if `groups:read` is missing:
   ```bash
   RESULT=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.list?types=public_channel,private_channel&limit=200")
   if echo "$RESULT" | jq -e '.ok == false and .error == "missing_scope"' >/dev/null 2>&1; then
     RESULT=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
       "https://slack.com/api/conversations.list?types=public_channel&limit=200")
   fi
   echo "$RESULT" | jq -r '.channels[] | "\(.id)\t\(.name)\t\(.num_members)\t\(.purpose.value // "")"'
   ```

3. Present the results showing: channel name, ID, member count, and purpose/topic.

4. Note which channels are in `AUTONOMOUS_CHANNELS` (from config) for the user's reference.
