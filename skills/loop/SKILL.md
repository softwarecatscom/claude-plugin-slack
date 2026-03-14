---
name: loop
description: Start a /loop 1m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 1-minute polling cycle that monitors configured Slack channels.

**Announce at start:** "Starting Slack polling loop (1m interval)."

## Setup

Use `/loop 1m` to schedule this prompt as a recurring cron job:

```
Use the `scc-slack:read` skill to check for new messages in Slack.
```

## Mode selection

When the loop fires, check `SLACK_POLL_DAEMON` in `~/.claude/slack.conf`:

- **`SLACK_POLL_DAEMON=1`**: Use the `scc-slack:daemon-loop` skill. It checks if the daemon is already running (singleton) — if yes, does nothing; if no, launches it in the background. The daemon handles polling internally and only wakes the agent when actionable messages arrive. **~98% token reduction.**
- **Unset or `0` (default)**: Use the `scc-slack:read` skill, which handles everything: fetching, filtering, evaluating, acting, and replying.

If there are no new messages, stay completely silent. Do not report that nothing happened.

## Pipeline reference

The read skill uses `slack-poll` under the hood. You do NOT need to call it directly — the read skill handles it. This is here for reference only:

```bash
# Locate scripts
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)

# Poll all configured channels (reads AUTONOMOUS_CHANNELS from ~/.claude/slack.conf)
"${SCRIPTS_DIR}/slack-poll"
```

**IMPORTANT:** Always use `slack-poll` via `ctx_execute` — it handles channel resolution, cursor management, mention filtering, AND thread scanning in one call. It also runs the heartbeat automatically at the end of each cycle. Using `ctx_execute` keeps the JSON output in the sandbox and protects your context window.

**DO NOT create a separate cron job for `/heartbeat`.** Heartbeat is built into `slack-poll` — if you are polling, you are heartbeating. A single polling cron is all you need.

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done, or use `scc-slack:stop`.
