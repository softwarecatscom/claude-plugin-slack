---
name: loop
description: Start a /loop 1m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 1-minute polling cycle that checks configured Slack channels for new messages. Stays silent when there are no new messages.

**Announce at start:** "Starting Slack polling loop (1m interval)."

## Setup

Use `/loop 1m` to schedule this prompt as a recurring cron job:

```
check slack — for each channel in AUTONOMOUS_CHANNELS from ~/.claude/slack.conf, fetch new messages since cursor
```

## When the loop fires

Each minute, the scheduled prompt runs. The agent should:

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

2. For each channel in `$AUTONOMOUS_CHANNELS` (comma-separated):
   - Get the channel ID
   - Fetch messages newer than the stored cursor
   - If new messages exist: use the `slack-read` skill to read and act on them
   - If no new messages: produce no output (stay quiet)

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done.
