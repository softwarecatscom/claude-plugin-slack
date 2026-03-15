---
name: loop
description: Start a /loop 2m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 2-minute polling cycle. The poller runs in the background and only wakes the agent when actionable messages arrive.

**Announce at start:** "Starting Slack polling loop (2m interval)."

## Setup

Use `/loop 2m` to schedule this prompt as a recurring cron job:

```
Use the `scc-slack:read` skill to check for new messages in Slack.
```

**DO NOT create a separate cron job for `/heartbeat`.** Heartbeat is built into the poller.

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
