---
name: loop
description: Start a /loop 1m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 1-minute polling cycle that monitors configured Slack channels via the long-poll daemon. The daemon runs in the background and only wakes the agent when actionable messages arrive.

**Announce at start:** "Starting Slack polling loop (1m interval)."

## Setup

Use `/loop 1m` to schedule this prompt as a recurring cron job:

```
Use the `scc-slack:daemon-loop` skill to check for new messages in Slack.
```

## When the loop fires

Each minute, the cron invokes `scc-slack:daemon-loop`. That skill checks if the daemon is already running — if yes, does nothing (zero cost). If the daemon stopped (it exits when it finds messages, or crashed), the skill re-launches it.

The daemon handles polling, filtering, heartbeat, and mention tracker internally. The agent only gets involved when there are actionable messages to process.

**DO NOT create a separate cron job for `/heartbeat`.** Heartbeat is built into the daemon — if you are polling, you are heartbeating.

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
