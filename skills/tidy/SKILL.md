---
name: tidy
description: Reset Slack cursor state and mark channels as read. Use when the user says "tidy slack", "reset slack cursors", "mark all read", or wants to clean up Slack tracking state.
---

# Tidy Slack State

Reset cursor tracking state and optionally mark all channels as read.

## Scripts

Load plugin config (provides SCRIPTS_DIR, DEFAULT_CHANNEL, AUTONOMOUS_CHANNELS):
```bash
source ~/.claude/slack.conf
```

**Prefer `ctx_execute` over Bash** when running scripts that produce output. This keeps raw output in the sandbox and protects your context window.

## Steps

1. Run the tidy script via `ctx_execute`, which handles cursor display, channel marking, and reset in one call:
   ```bash
   "${SCRIPTS_DIR}/slack-tidy"
   ```

   For a preview without making changes:
   ```bash
   "${SCRIPTS_DIR}/slack-tidy" --dry-run
   ```

2. Report what was tidied based on the script output.
