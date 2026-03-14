---
name: channels
description: List Slack channels the bot has access to. Use when the user says "list channels", "slack channels", "what channels", or wants to see available Slack channels.
---

# List Slack Channels

List all public channels (and private channels if `groups:read` scope is granted).

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

**ALWAYS use `slack-channels` to list channels.** Do NOT call `conversations.list` directly with curl.

## Steps

1. Use the `scc-slack:config` skill to load plugin config.

2. List channels using the script:
   ```bash
   "${SCRIPTS_DIR}/slack-channels"
   ```
   To filter by name: `"${SCRIPTS_DIR}/slack-channels" --filter PATTERN`

3. Present the results showing: channel name, ID, member count, and purpose/topic.

4. Note which channels are in `AUTONOMOUS_CHANNELS` (from config) for the user's reference.
