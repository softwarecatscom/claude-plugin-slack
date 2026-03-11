---
name: config
description: Load Slack plugin configuration. Use when the user says "slack config", "show slack settings", or when any other skill needs DEFAULT_CHANNEL or AUTONOMOUS_CHANNELS.
---

# Load Slack Config

Load plugin configuration from `~/.claude/slack.conf`.

## Steps

1. Read the config file:
   ```bash
   cat ~/.claude/slack.conf 2>/dev/null
   ```

2. If the file is missing, tell the user to run `/scc-slack:setup` first.

3. Parse the following variables from the output:
   - `DEFAULT_CHANNEL` — the default channel for send/read operations
   - `AUTONOMOUS_CHANNELS` — comma-separated list of channels to monitor in polling mode

4. Return the parsed values. When invoked by another skill, make these variables available for subsequent steps.
