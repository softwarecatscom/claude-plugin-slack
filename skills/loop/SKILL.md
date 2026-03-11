---
name: loop
description: Start a /loop 1m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 1-minute polling cycle that monitors configured Slack channels. Delegates all message handling to the `scc-slack:read` skill.

**Announce at start:** "Starting Slack polling loop (1m interval)."

## Setup

Use `/loop 1m` to schedule this prompt as a recurring cron job:

```
check slack — for each channel in AUTONOMOUS_CHANNELS, read new messages
```

## When the loop fires

Each minute, the scheduled prompt runs. The agent should:

1. Use the `scc-slack:config` skill to load `AUTONOMOUS_CHANNELS`.

2. For each channel in `AUTONOMOUS_CHANNELS` (comma-separated), use the `scc-slack:read` skill. Read handles everything: fetching, filtering, evaluating, acting, and replying.

3. If read produces no output for any channel (no new messages), stay completely silent. Do not report that nothing happened.

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
