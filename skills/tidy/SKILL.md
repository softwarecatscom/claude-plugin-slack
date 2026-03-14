---
name: tidy
description: Reset Slack cursor state and mark channels as read. Use when the user says "tidy slack", "reset slack cursors", "mark all read", or wants to clean up Slack tracking state.
---

# Tidy Slack State

Reset cursor tracking state and optionally mark all channels as read.

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Steps

1. Run the tidy script, which handles cursor display, channel marking, and reset in one call:
   ```bash
   "${SCRIPTS_DIR}/slack-tidy"
   ```

   For a preview without making changes:
   ```bash
   "${SCRIPTS_DIR}/slack-tidy" --dry-run
   ```

2. Report what was tidied based on the script output.
