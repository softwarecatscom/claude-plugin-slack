---
name: slack-channels
description: List Slack channels the bot has access to. Use when the user says "list channels", "slack channels", "what channels", or wants to see available Slack channels.
---

# List Slack Channels

List all channels the bot is a member of.

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. List channels:
   ```bash
   slack channels list
   ```

3. Present the results showing: channel name, ID, member count, and purpose/topic.

4. Note which channels are in `AUTONOMOUS_CHANNELS` (from config) for the user's reference.
