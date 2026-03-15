---
name: loop
description: Start a /loop 2m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 2-minute polling cycle that monitors configured Slack channels via the slack poller. The poller runs in the background and only wakes the agent when actionable messages arrive.

**Announce at start:** "Starting Slack polling loop (2m interval)."

## Setup

Use `/loop 2m` to schedule this prompt as a recurring cron job:

```
Use the `scc-slack:daemon-loop` skill to check for new messages in Slack.
```

## When the loop fires

Every 2 minutes, the cron invokes `scc-slack:daemon-loop`. That skill checks if the poller is already running — if yes, does nothing (zero cost). If the poller stopped (it exits when it finds messages, or crashed), the skill re-launches it.

The poller polls Slack internally every 30s regardless of the cron interval. The cron only controls re-launch latency.

**DO NOT create a separate cron job for `/heartbeat`.** Heartbeat is built into the poller — if you are polling, you are heartbeating.

## Reference

For detailed architecture, message format, processing rules, and troubleshooting: read `docs/polling-guide.md` in the plugin repo (once per session, not every cycle).

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
