---
name: lookup
description: Look up a Slack channel or user by name. Use when the user says "lookup channel", "find user", "who is @name", "what channel is #name", or when any other skill needs to resolve a channel or user.
---

# Slack Lookup

Resolve a channel name to its ID/details, or a user name to their ID/profile.

## Arguments

- `query` — a channel name prefixed with `#` (e.g., `#general`) or a user name prefixed with `@` (e.g., `@christo`). The prefix can be omitted if the intent is clear from context.

## Steps

1. Use the `scc-slack:token` skill to load `SLACK_TOKEN`.

2. **If the query is a channel** (`#` prefix or channel context):

   Resolve via the Slack API:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.list?types=public_channel,private_channel&limit=200" \
     | jq -r '.channels[] | select(.name=="<channel_name>") | "\(.id)\t\(.name)\t\(.num_members)\t\(.purpose.value // "")"'
   ```
   If the call fails with `missing_scope`, fall back to public channels only:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.list?types=public_channel&limit=200" \
     | jq -r '.channels[] | select(.name=="<channel_name>") | "\(.id)\t\(.name)\t\(.num_members)\t\(.purpose.value // "")"'
   ```

   Return the channel ID, name, member count, and purpose.

3. **If the query is a user** (`@` prefix or user context):

   Resolve via the Slack API:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" "https://slack.com/api/users.list" \
     | jq -r '.members[] | "\(.id)\t\(.name)\t\(.profile.display_name)\t\(.profile.real_name)"'
   ```
   Match the query against `name`, `display_name`, or `real_name` (case-insensitive). Return the user ID, username, display name, and real name.

4. If no match is found, report that and suggest checking the spelling or running `scc-slack:channels` to list available channels.
