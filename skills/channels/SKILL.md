---
name: channels
description: List Slack channels the bot has access to. Use when the user says "list channels", "slack channels", "what channels", or wants to see available Slack channels.
---

# List Slack Channels

List all public channels (and private channels if `groups:read` scope is granted).

## Steps

1. Use the `scc-slack:token` skill to load `SLACK_TOKEN`.

2. Use the `scc-slack:config` skill to load plugin config.

3. List channels via the Slack API. Try public+private first, fall back to public-only if `groups:read` is missing:
   ```bash
   RESULT=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.list?types=public_channel,private_channel&limit=200")
   if echo "$RESULT" | jq -e '.ok == false and .error == "missing_scope"' >/dev/null 2>&1; then
     RESULT=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
       "https://slack.com/api/conversations.list?types=public_channel&limit=200")
   fi
   echo "$RESULT" | jq -r '.channels[] | "\(.id)\t\(.name)\t\(.num_members)\t\(.purpose.value // "")"'
   ```

4. Present the results showing: channel name, ID, member count, and purpose/topic.

5. Note which channels are in `AUTONOMOUS_CHANNELS` (from config) for the user's reference.
