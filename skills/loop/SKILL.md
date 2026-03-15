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
Check if the slack poller is running. Run: source ~/.claude/slack.conf && "${SCRIPTS_DIR}/slack-poll" status. If "stopped", launch it with Bash(command: "source ~/.claude/slack.conf && ${SCRIPTS_DIR}/slack-poll run", description: "slack-poll", run_in_background: true, timeout: 600000). If "running", do nothing and say nothing. When a background task completes, Read (not cat) the .output file, then follow the Agent Algorithm in the scc-slack:read skill to process the messages. Do NOT invoke /scc-slack:read as a polling mechanism — the poller handles polling.
```

## When the loop fires

Every 2 minutes, the cron fires. It checks if the poller is running — if yes, does nothing (zero cost). If stopped, launches the poller in the background.

The poller polls Slack internally every 30s regardless of the cron interval. The cron only controls re-launch latency.

**DO NOT create a separate cron job for `/heartbeat`.** Heartbeat is built into the poller — if you are polling, you are heartbeating.

## Reference

For detailed architecture, message format, processing rules, and troubleshooting: read `docs/polling-guide.md` in the plugin repo (once per session, not every cycle).

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
